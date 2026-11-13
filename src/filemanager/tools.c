/* Optional terminal tools, discovered without blocking the file manager startup.
 * Architecture: doc/decisions/0001-terminal-tools.md. */
#include <config.h>

#include <errno.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>

#include "lib/global.h"
#include "lib/widget.h"
#include "lib/tty/key.h"
#include "lib/tty/tty.h"
#include "lib/util.h"
#include "lib/vfs/vfs.h"
#include "src/execute.h"
#include "filemanager.h"
#include "panel.h"
#include "tools.h"

#define DETACH_HINT "Detach: #{s/C-/Ctrl+/;s/M-/Alt+/:prefix}, then d (session keeps running)"

static const char *const tool_names[] = { "tmux",   "hermes", "pi",       "opencode",
                                          "claude", "codex",  "codex-cli" };
static const char *const tool_labels[] = { "tmux",     "Hermes",      "Pi",
                                           "OpenCode", "Claude Code", "Codex CLI" };
static gboolean available[G_N_ELEMENTS (tool_names)];
static gboolean have_sessions;
static gboolean discovery_ready;
static int discovery_fd = -1;
static GString *discovery_output;

static int
tools_discovered (int fd, void *data)
{
    char buffer[4096];
    ssize_t n;

    (void) data;
    while ((n = read (fd, buffer, sizeof (buffer))) > 0)
        g_string_append_len (discovery_output, buffer, n);
    if (n < 0 && (errno == EAGAIN || errno == EINTR))
        return 0;

    {
        char **lines = g_strsplit (discovery_output->str, "\n", -1);
        guint i, j;

        for (i = 0; lines[i] != NULL; i++)
        {
            for (j = 0; j < G_N_ELEMENTS (tool_names); j++)
                if (strcmp (lines[i], tool_names[j]) == 0)
                    available[j] = TRUE;
            if (strcmp (lines[i], "sessions") == 0)
                have_sessions = TRUE;
        }
        g_strfreev (lines);
    }
    discovery_ready = TRUE;
    delete_select_channel (fd);
    close (fd);
    discovery_fd = -1;
    g_string_free (discovery_output, TRUE);
    discovery_output = NULL;
    return 0;
}

void
tools_init (void)
{
    char *argv[] = { (char *) "sh", (char *) "-c",
                     (char *) "for t in tmux hermes pi opencode claude codex codex-cli; do "
                              "command -v \"$t\" >/dev/null 2>&1 && printf '%s\\n' \"$t\"; done; "
                              "if command -v tmux >/dev/null 2>&1 && "
                              "tmux list-sessions >/dev/null 2>&1; then printf 'sessions\\n'; fi",
                     NULL };

    static gboolean path_initialized = FALSE;

    if (!path_initialized)
    {
        const char *existing_path = g_getenv ("PATH");
        GString *path = g_string_new (existing_path != NULL && *existing_path != '\0'
                                          ? existing_path
                                          : "/usr/local/bin:/usr/bin:/bin");
        const char *home = g_get_home_dir ();
        guint i;

        g_string_append_printf (path, ":%s/.local/bin:%s/.opencode/bin:%s/.hermes/bin", home, home,
                                home);
        for (i = 1; i < G_N_ELEMENTS (tool_labels); i++)
            g_string_append_printf (path, ":%s/.local/share/mymc/tools/%s/bin", home,
                                    tool_names[i]);
        g_setenv ("PATH", path->str, TRUE);
        g_string_free (path, TRUE);
        path_initialized = TRUE;
    }
    memset (available, 0, sizeof (available));
    have_sessions = FALSE;
    discovery_ready = FALSE;
    if (!g_spawn_async_with_pipes (NULL, argv, NULL,
                                   G_SPAWN_SEARCH_PATH | G_SPAWN_STDERR_TO_DEV_NULL, NULL, NULL,
                                   NULL, NULL, &discovery_fd, NULL, NULL))
    {
        discovery_ready = TRUE;
        return;
    }
    if (fcntl (discovery_fd, F_SETFL, O_NONBLOCK) == -1)
    {
        close (discovery_fd);
        discovery_fd = -1;
        discovery_ready = TRUE;
        return;
    }
    discovery_output = g_string_new (NULL);
    add_select_channel (discovery_fd, tools_discovered, NULL);
}

void
tools_done (void)
{
    if (discovery_fd != -1)
    {
        delete_select_channel (discovery_fd);
        close (discovery_fd);
        discovery_fd = -1;
    }
    if (discovery_output != NULL)
    {
        g_string_free (discovery_output, TRUE);
        discovery_output = NULL;
    }
}

/* A vanished server/session is normal; always refresh before offering an attachment. */
static char *
tmux_sessions (gboolean formatted)
{
    char *argv[] = { (char *) "tmux", (char *) "list-sessions", (char *) "-F",
                     (char *) "#{session_id}\t#{session_name}", NULL };
    char *output = NULL;
    gint status;

    if (!formatted)
        argv[2] = NULL;
    have_sessions =
        g_spawn_sync (NULL, argv, NULL, G_SPAWN_SEARCH_PATH | G_SPAWN_STDERR_TO_DEV_NULL, NULL,
                      NULL, &output, NULL, &status, NULL)
        && g_spawn_check_wait_status (status, NULL) && output != NULL && *output != '\0';
    if (!have_sessions)
        g_clear_pointer (&output, g_free);
    return output;
}

static char *
tools_directory (void)
{
    if (current_panel != NULL && vfs_file_is_local (current_panel->cwd_vpath))
    {
        const file_entry_t *fe = panel_current_entry (current_panel);
        const char *cwd = vfs_path_as_str (current_panel->cwd_vpath);

        if (fe != NULL && S_ISDIR (fe->st.st_mode) && strcmp (fe->fname->str, "..") != 0)
            return g_build_filename (cwd, fe->fname->str, NULL);
        return g_strdup (cwd);
    }
    return g_strdup (g_get_home_dir ());
}

/* Session options keep the hint local and the format follows changes to the prefix key. */
static void
tools_connect (const char *prepare)
{
    char *command = g_strdup_printf (
        "%s && status=$(tmux show-options -Av -t \"$session\" status-right) && "
        "{ case \"$status\" in *'" DETACH_HINT "'*) ;; "
        "*) tmux set-option -t \"$session\" status-right \"" DETACH_HINT " | $status\" ;; "
        "esac; } && tmux set-option -t \"$session\" status on && "
        "tmux set-option -t \"$session\" status-right-length 100 && "
        "tmux %s -t \"$session\"",
        prepare, g_getenv ("TMUX") != NULL ? "switch-client" : "attach-session");
    char *script = g_shell_quote (command);
    char *launcher = g_strdup_printf ("sh -c %s", script);

    shell_execute (launcher, EXECUTE_INTERNAL);
    g_free (launcher);
    g_free (script);
    g_free (command);
}

static void
tools_launch (const char *tool)
{
    char *directory = tools_directory ();
    char *quoted = g_shell_quote (directory);
    char *prepare;

    /* All tool names come from the fixed table above. Never interpolate session names. */
    prepare = g_strdup_printf ("session=$(tmux new-session -d -P -F '#{session_id}' -c %s %s)",
                               quoted, tool != NULL ? tool : "");
    tools_connect (prepare);
    g_free (prepare);
    g_free (quoted);
    g_free (directory);
}

static void
tools_attach (void)
{
    char *sessions = tmux_sessions (TRUE);
    char **lines;
    guint count = 0;
    int selected = 0;

    if (sessions == NULL)
    {
        message (D_NORMAL, _ ("tmux"), "%s", _ ("No running sessions."));
        return;
    }
    lines = g_strsplit (g_strchomp (sessions), "\n", -1);
    while (lines[count] != NULL)
        count++;
    if (count > 1)
    {
        Listbox *list = listbox_window_new (MIN ((int) count, LINES - 6), MIN (60, COLS - 6),
                                            _ ("Attach tmux session"), NULL);
        guint i;

        for (i = 0; i < count; i++)
        {
            char *name = strchr (lines[i], '\t');
            LISTBOX_APPEND_TEXT (list, 0, name != NULL ? name + 1 : lines[i], NULL, FALSE);
        }
        selected = listbox_run (list);
    }
    if (selected >= 0 && (guint) selected < count)
    {
        char *tab = strchr (lines[selected], '\t');
        char *target, *prepare;

        if (tab != NULL)
            *tab = '\0';
        target = g_shell_quote (lines[selected]);
        prepare = g_strdup_printf ("session=%s", target);
        tools_connect (prepare);
        g_free (prepare);
        g_free (target);
    }
    g_strfreev (lines);
    g_free (sessions);
}

static gboolean
tools_ready (gboolean require_tmux)
{
    if (!discovery_ready)
    {
        message (D_NORMAL, _ ("Tools"), "%s",
                 _ ("Checking installed tools in the background. Please try again shortly."));
        return FALSE;
    }
    if (require_tmux && !available[0])
    {
        message (D_NORMAL, _ ("tmux is not installed"), "%s",
                 _ ("Choose Tools > Install / update / purge > tmux > Install first."));
        return FALSE;
    }
    return TRUE;
}

static gboolean
tools_tmux_command (char **argv)
{
    char *error = NULL;
    GError *spawn_error = NULL;
    gint status;
    gboolean ok;

    ok = g_spawn_sync (NULL, argv, NULL, G_SPAWN_SEARCH_PATH, NULL, NULL, NULL, &error, &status,
                       &spawn_error);
    if (ok)
        ok = g_spawn_check_wait_status (status, &spawn_error);
    if (!ok)
        message (D_ERROR, _ ("tmux"), "%s",
                 error != NULL && *error != '\0' ? error
                     : spawn_error != NULL       ? spawn_error->message
                                                 : _ ("Command failed."));
    g_clear_error (&spawn_error);
    g_free (error);
    return ok;
}

static void
tools_manage_sessions (void)
{
    char *sessions = tmux_sessions (TRUE);
    char **lines;
    guint count = 0, i;
    int selected, action;
    Listbox *list;
    char *name, *target;

    if (sessions == NULL)
    {
        message (D_NORMAL, _ ("Manage sessions"), "%s", _ ("No running sessions."));
        return;
    }
    lines = g_strsplit (g_strchomp (sessions), "\n", -1);
    while (lines[count] != NULL)
        count++;
    list = listbox_window_new (MIN ((int) count, LINES - 6), MIN (64, COLS - 6),
                               _ ("Manage running sessions"), NULL);
    for (i = 0; i < count; i++)
    {
        name = strchr (lines[i], '\t');
        LISTBOX_APPEND_TEXT (list, 0, name != NULL ? name + 1 : lines[i], NULL, FALSE);
    }
    selected = listbox_run (list);
    if (selected < 0 || (guint) selected >= count)
        goto out;
    target = lines[selected];
    name = strchr (target, '\t');
    if (name != NULL)
        *name++ = '\0';
    else
        name = target;
    list = listbox_window_new (4, MIN (64, COLS - 6), name, NULL);
    LISTBOX_APPEND_TEXT (list, 'a', _ ("Attach"), NULL, FALSE);
    LISTBOX_APPEND_TEXT (list, 'r', _ ("Rename..."), NULL, FALSE);
    LISTBOX_APPEND_TEXT (list, 'd', _ ("Detach all clients..."), NULL, FALSE);
    LISTBOX_APPEND_TEXT (list, 's', _ ("Stop session (ends running programs)..."), NULL, FALSE);
    action = listbox_run (list);
    if (action == 0)
    {
        char *quoted = g_shell_quote (target);
        char *prepare = g_strdup_printf ("session=%s", quoted);
        tools_connect (prepare);
        g_free (prepare);
        g_free (quoted);
    }
    else if (action == 1)
    {
        char *new_name = input_dialog (_ ("Rename session"), _ ("New session name:"),
                                       "tmux-session-name", name, INPUT_COMPLETE_NONE);
        if (new_name != NULL && *new_name != '\0')
        {
            char *argv[] = { (char *) "tmux",
                             (char *) "rename-session",
                             (char *) "-t",
                             target,
                             (char *) "--",
                             new_name,
                             NULL };
            (void) tools_tmux_command (argv);
        }
        g_free (new_name);
    }
    else if (action == 2 || action == 3)
    {
        char *prompt = g_strdup_printf (
            action == 2 ? _ ("Detach every client from '%s'? Its programs will keep running.")
                        : _ ("Stop '%s'? All programs running in this session will end."),
            name);
        if (query_dialog (_ ("Confirm session action"), prompt, D_NORMAL, 2, _ ("&Cancel"),
                          action == 2 ? _ ("&Detach clients") : _ ("&Stop session"))
            == 1)
        {
            char *argv[] = { (char *) "tmux",
                             (char *) (action == 2 ? "detach-client" : "kill-session"),
                             (char *) (action == 2 ? "-s" : "-t"), target, NULL };
            (void) tools_tmux_command (argv);
        }
        g_free (prompt);
    }
out:
    g_strfreev (lines);
    g_free (sessions);
}

void
tools_sessions_cmd (void)
{
    Listbox *list;
    int actions[4], count = 0, selected;
    char *sessions;

    if (!tools_ready (TRUE))
        return;
    sessions = tmux_sessions (FALSE);
    g_free (sessions);
    list = listbox_window_new (4, MIN (64, COLS - 6), _ ("Sessions"), NULL);
    LISTBOX_APPEND_TEXT (list, 'l', _ ("List running sessions (tmux ls)"), NULL, FALSE);
    actions[count++] = 0;
    if (have_sessions)
    {
        LISTBOX_APPEND_TEXT (list, 'a', _ ("Attach to a running session..."), NULL, FALSE);
        actions[count++] = 1;
    }
    LISTBOX_APPEND_TEXT (list, 'n', _ ("New session in this folder"), NULL, FALSE);
    actions[count++] = 2;
    if (have_sessions)
    {
        LISTBOX_APPEND_TEXT (list, 'm', _ ("Manage running sessions..."), NULL, FALSE);
        actions[count++] = 3;
    }
    selected = listbox_run (list);
    if (selected < 0 || selected >= count)
        return;
    switch (actions[selected])
    {
    case 0:
        sessions = tmux_sessions (FALSE);
        message (D_NORMAL, _ ("Running sessions"), "%s",
                 sessions != NULL ? sessions : _ ("No running sessions."));
        g_free (sessions);
        break;
    case 1:
        tools_attach ();
        break;
    case 2:
        tools_launch (NULL);
        break;
    case 3:
        tools_manage_sessions ();
        break;
    default:
        break;
    }
}

void
tools_assistants_cmd (void)
{
    Listbox *list;
    int actions[6], count = 0, selected;
    guint i;

    if (!tools_ready (TRUE))
        return;
    list = listbox_window_new (5, MIN (64, COLS - 6), _ ("Assistants - new session in this folder"),
                               NULL);
    for (i = 1; i < G_N_ELEMENTS (tool_labels); i++)
        if (available[i] || (i == 5 && available[6]))
        {
            LISTBOX_APPEND_TEXT (list, 0, tool_labels[i], NULL, FALSE);
            actions[count++] = i == 5 && !available[5] ? 6 : (int) i;
        }
    if (count == 0)
    {
        /* The empty list never runs; still release its dialog and allocation. */
        widget_destroy (WIDGET (list->dlg));
        g_free (list);
        message (
            D_NORMAL, _ ("Assistants"), "%s",
            _ ("No assistants found. Choose Tools > Install / update / purge to install one."));
        return;
    }
    selected = listbox_run (list);
    if (selected >= 0 && selected < count)
        tools_launch (tool_names[actions[selected]]);
}

void
tools_manage_cmd (void)
{
    Listbox *list;
    guint i;
    int selected, action;
    char *helper, *label;
    const char *operations[] = { "install", "update", "purge", "status" };
    char *plan_output = NULL, *error_output = NULL;
    gint status;
    gboolean ok;

    if (!tools_ready (FALSE))
        return;
    list = listbox_window_new (6, MIN (64, COLS - 6), _ ("Install / update / purge"), NULL);
    for (i = 0; i < G_N_ELEMENTS (tool_labels); i++)
    {
        gboolean installed = available[i] || (i == 5 && available[6]);
        label = g_strdup_printf ("%s  [%s]", tool_labels[i],
                                 installed ? _ ("installed") : _ ("not installed"));
        LISTBOX_APPEND_TEXT (list, 0, label, NULL, FALSE);
        g_free (label);
    }
    selected = listbox_run (list);
    if (selected < 0 || (guint) selected >= G_N_ELEMENTS (tool_labels))
        return;
    list = listbox_window_new (4, MIN (64, COLS - 6), tool_labels[selected], NULL);
    LISTBOX_APPEND_TEXT (list, 'i', _ ("Install"), NULL, FALSE);
    LISTBOX_APPEND_TEXT (list, 'u', _ ("Update"), NULL, FALSE);
    LISTBOX_APPEND_TEXT (list, 'p', _ ("Purge program, settings, credentials and history..."), NULL,
                         FALSE);
    LISTBOX_APPEND_TEXT (list, 's', _ ("Installation details"), NULL, FALSE);
    action = listbox_run (list);
    if (action < 0 || action > 3)
        return;
    helper = g_build_filename (mc_global.share_data_dir, "mymc-tool", NULL);
    {
        char *argv[] = { (char *) "sh",
                         helper,
                         (char *) "--plan",
                         (char *) operations[action],
                         (char *) tool_names[selected],
                         NULL };
        ok = g_spawn_sync (NULL, argv, NULL, G_SPAWN_SEARCH_PATH, NULL, NULL, &plan_output,
                           &error_output, &status, NULL);
        if (ok)
            ok = g_spawn_check_wait_status (status, NULL);
    }
    if (!ok)
        message (D_ERROR, tool_labels[selected], "%s",
                 error_output != NULL && *error_output != '\0'
                     ? error_output
                     : _ ("Could not prepare this operation."));
    else if (action == 3)
        message (D_NORMAL, _ ("Installation details"), "%s", plan_output);
    else if (query_dialog (action == 2 ? _ ("Permanently purge tool and all data?")
                                       : _ ("Confirm tool maintenance"),
                           plan_output, D_NORMAL, 2, _ ("&Cancel"),
                           action == 2 ? _ ("&Purge everything") : _ ("&Continue"))
             == 1)
    {
        char *quoted = g_shell_quote (helper);
        char *command = g_strdup_printf (
            "sh %s %s %s; result=$?; "
            "printf '\\nOperation finished (exit %%s). Press Enter to return to MC.' \"$result\"; "
            "IFS= read -r answer; exit \"$result\"",
            quoted, operations[action], tool_names[selected]);
        char *script = g_shell_quote (command);
        char *launcher = g_strdup_printf ("sh -c %s", script);

        shell_execute (launcher, EXECUTE_INTERNAL);
        g_free (launcher);
        g_free (script);
        g_free (command);
        g_free (quoted);
        tools_done ();
        tools_init ();
    }
    g_free (plan_output);
    g_free (error_output);
    g_free (helper);
}

void
tools_cmd (void)
{
    Listbox *list;
    int selected;

    list = listbox_window_new (3, MIN (64, COLS - 6), _ ("Tools"), NULL);
    LISTBOX_APPEND_TEXT (list, 's', _ ("Sessions..."), NULL, FALSE);
    LISTBOX_APPEND_TEXT (list, 'a', _ ("Assistants..."), NULL, FALSE);
    LISTBOX_APPEND_TEXT (list, 'i', _ ("Install / update / purge..."), NULL, FALSE);
    selected = listbox_run (list);
    if (selected == 0)
        tools_sessions_cmd ();
    else if (selected == 1)
        tools_assistants_cmd ();
    else if (selected == 2)
        tools_manage_cmd ();
}
