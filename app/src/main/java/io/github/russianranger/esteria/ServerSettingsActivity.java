package io.github.russianranger.esteria;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import io.github.russianranger.esteria.core.server.ServerConfigFile;
import io.github.russianranger.esteria.core.server.ServerConfigOverrides;
import io.github.russianranger.esteria.core.server.ServerConfigRules;
import io.github.russianranger.esteria.runtime.ServerSettingsStore;
import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Browse and change the local server's worldserver and module settings. Changes are saved in the app and
 * reach the next server start as AzerothCore overrides; the verified configuration files are never edited. */
public final class ServerSettingsActivity extends Activity {
    private static final int MUTED = 0xff9aa59c, WARN = 0xffe0a86a, LIST = 0xff16201d;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final List<ServerConfigFile> files = new ArrayList<>();
    private final List<Object> rows = new ArrayList<>();
    private ServerConfigRules rules;
    private ServerConfigOverrides overrides;
    private Spinner fileChoice;
    private EditText search;
    private CheckBox changedOnly;
    private TextView summary;
    private ListView list;
    private Button resetAll;
    private final RowAdapter adapter = new RowAdapter();

    @Override protected void onCreate(Bundle savedState) {
        super.onCreate(savedState);
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(16), dp(12), dp(16), dp(8));
        page.setBackgroundColor(0xff10161c);
        TextView title = text("Server settings", 26, RealmLauncher.GOLD);
        title.setTypeface(getResources().getFont(R.font.cinzel), Typeface.BOLD);
        page.addView(title);
        summary = text("Loading the server settings…", 14, RealmLauncher.PAPER);
        summary.setPadding(0, dp(2), 0, dp(8));
        page.addView(summary);

        LinearLayout filters = new LinearLayout(this);
        filters.setOrientation(LinearLayout.HORIZONTAL);
        filters.setGravity(Gravity.CENTER_VERTICAL);
        fileChoice = new Spinner(this);
        fileChoice.setEnabled(false);
        filters.addView(fileChoice, new LinearLayout.LayoutParams(0, -2, 1));
        changedOnly = new CheckBox(this);
        changedOnly.setText("Changed only");
        changedOnly.setTextColor(RealmLauncher.PAPER);
        changedOnly.setOnCheckedChangeListener((view, checked) -> refresh());
        filters.addView(changedOnly);
        page.addView(filters);

        search = new EditText(this);
        search.setHint("Search names and descriptions");
        search.setHintTextColor(MUTED);
        search.setTextColor(Color.WHITE);
        search.setSingleLine(true);
        search.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        search.addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence s, int a, int b, int c) { }
            public void onTextChanged(CharSequence s, int a, int b, int c) { }
            public void afterTextChanged(Editable s) { refresh(); }
        });
        page.addView(search);

        list = new ListView(this);
        list.setBackgroundColor(LIST);
        list.setDividerHeight(dp(1));
        list.setAdapter(adapter);
        list.setOnItemClickListener((parent, view, position, id) -> {
            Object row = rows.get(position);
            if (row instanceof ServerConfigFile.Setting) edit((ServerConfigFile.Setting) row);
        });
        page.addView(list, new LinearLayout.LayoutParams(-1, 0, 1));

        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        resetAll = new Button(this);
        resetAll.setText("Reset all changes");
        resetAll.setAllCaps(false);
        resetAll.setEnabled(false);
        resetAll.setOnClickListener(view -> confirmResetAll());
        actions.addView(resetAll, new LinearLayout.LayoutParams(0, -2, 1));
        Button done = new Button(this);
        done.setText("Done");
        done.setAllCaps(false);
        done.setOnClickListener(view -> finish());
        actions.addView(done, new LinearLayout.LayoutParams(0, -2, 1));
        page.addView(actions);
        setContentView(page);
        worker.execute(this::load);
    }

    @Override protected void onDestroy() {
        worker.shutdownNow();
        super.onDestroy();
    }

    private void load() {
        String problem = null;
        ServerConfigRules loadedRules = null;
        ServerConfigOverrides loadedOverrides = null;
        List<ServerConfigFile> loaded = new ArrayList<>();
        try {
            loadedRules = ServerSettingsStore.rules(this);
            loadedOverrides = ServerSettingsStore.overrides(this);
            Path generation = ServerSettingsStore.activeGeneration(this);
            if (generation == null) problem = "Start the local game once, then come back. The settings are read from the prepared world.";
            else for (String name : ServerSettingsStore.files(generation, loadedRules)) {
                try { loaded.add(ServerSettingsStore.read(generation, name, loadedRules)); }
                catch (IOException unreadable) { /* Skip a file that cannot be read; the others stay usable. */ }
            }
            if (problem == null && loaded.isEmpty()) problem = "No server settings files were found in the prepared world.";
        } catch (IOException | RuntimeException error) {
            problem = "The server settings could not be read: " + error.getMessage();
        }
        final String message = problem;
        final ServerConfigRules finalRules = loadedRules;
        final ServerConfigOverrides finalOverrides = loadedOverrides;
        ui.post(() -> {
            if (isFinishing() || isDestroyed()) return;
            rules = finalRules; overrides = finalOverrides;
            files.clear(); files.addAll(loaded);
            if (message != null) { summary.setText(message); return; }
            List<String> labels = new ArrayList<>();
            for (ServerConfigFile file : files) labels.add(fileLabel(file.name));
            labels.add("All files");
            ArrayAdapter<String> choices = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, labels) {
                @Override public View getView(int position, View convert, ViewGroup parent) {
                    TextView view = (TextView) super.getView(position, convert, parent);
                    view.setTextColor(RealmLauncher.PAPER); view.setTextSize(16);
                    return view;
                }
            };
            choices.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
            fileChoice.setAdapter(choices);
            fileChoice.setEnabled(true);
            fileChoice.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
                public void onItemSelected(AdapterView<?> parent, View view, int position, long id) { refresh(); }
                public void onNothingSelected(AdapterView<?> parent) { }
            });
            refresh();
        });
    }

    private static String fileLabel(String name) {
        if (name.equals("modules/playerbots.conf")) return "Playerbots";
        return ServerConfigFile.fallbackSection(name);
    }

    private void refresh() {
        if (rules == null || overrides == null || files.isEmpty()) return;
        int selected = fileChoice.getSelectedItemPosition();
        boolean all = selected < 0 || selected >= files.size();
        String query = search.getText().toString().trim().toLowerCase(Locale.ROOT);
        rows.clear();
        String lastHeading = null;
        for (int index = 0; index < files.size(); index++) {
            if (!all && index != selected) continue;
            ServerConfigFile file = files.get(index);
            for (ServerConfigFile.Setting setting : file.settings) {
                if (changedOnly.isChecked() && overrides.get(setting.file, setting.key) == null) continue;
                if (!query.isEmpty() && !setting.key.toLowerCase(Locale.ROOT).contains(query) &&
                        !setting.help.toLowerCase(Locale.ROOT).contains(query) &&
                        !(rules.managed(setting.key) ? "" : setting.value.toLowerCase(Locale.ROOT)).contains(query)) continue;
                String heading = (all ? fileLabel(file.name) + " · " : "") + setting.section;
                if (!heading.equals(lastHeading)) { rows.add(heading); lastHeading = heading; }
                rows.add(setting);
            }
        }
        adapter.notifyDataSetChanged();
        int changed = overrides.count();
        summary.setText((changed == 0 ? "No changes" : changed + (changed == 1 ? " setting changed" : " settings changed")) +
            " · changes apply the next time you start the local game. Settings marked Esteria are managed by the app.");
        resetAll.setEnabled(changed > 0);
    }

    private String shown(ServerConfigFile.Setting setting, String value) {
        if (value == null) return "";
        switch (setting.kind) {
            case SWITCH: return ServerConfigFile.Setting.switchedOn(value) ? "On" : "Off";
            case CHOICE: {
                String label = setting.choiceLabel(value);
                return label == null ? value : value + " · " + label;
            }
            default: return value.isEmpty() ? "(empty)" : value;
        }
    }

    private String detail(ServerConfigFile.Setting setting) {
        if (rules.managed(setting.key)) return "Managed by Esteria";
        String mine = overrides.get(setting.file, setting.key), launch = rules.launchDefault(setting.key);
        String base = launch != null ? launch : setting.value;
        StringBuilder out = new StringBuilder();
        if (mine != null) out.append("Your value: ").append(shown(setting, mine)).append("   ·   default ").append(shown(setting, base));
        else out.append(shown(setting, base));
        if (launch != null && mine == null) out.append("   ·   Esteria's lighter tick (file ").append(setting.value).append(')');
        if (rules.heavy(setting.key)) out.append("   ·   can raise heat");
        return out.toString();
    }

    private void edit(ServerConfigFile.Setting setting) {
        if (rules.managed(setting.key)) {
            new AlertDialog.Builder(this, R.style.RealmDialog).setTitle(setting.key)
                .setMessage("Esteria manages this setting, so it cannot be changed here. It covers the database, paths, network, " +
                    "logging and the modules the stock 3.3.5a profile keeps off.\n\n" + setting.help)
                .setPositiveButton("OK", null).show();
            return;
        }
        String mine = overrides.get(setting.file, setting.key), launch = rules.launchDefault(setting.key);
        String base = launch != null ? launch : setting.value, current = mine != null ? mine : base;
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(20), dp(8), dp(20), dp(4));
        StringBuilder about = new StringBuilder(fileLabel(setting.file)).append(" · ").append(setting.section);
        about.append("\nDefault: ").append(shown(setting, base));
        if (launch != null) about.append(" (Esteria's lighter tick; the file says ").append(setting.value).append(')');
        if (rules.heavy(setting.key)) about.append("\nRaising this can increase CPU load, heat and start-up time.");
        if (setting.key.startsWith("AiPlayerbot.") && (setting.key.contains("RandomBot") || setting.key.contains("AddClassAccount")))
            about.append("\nRandom bots have not been tested on the Thor. The first start creates their accounts and characters, " +
                "which takes longer, and every active bot costs CPU. Start with a few (5 to 10).");
        TextView info = text(about.toString(), 14, RealmLauncher.GOLD);
        body.addView(info);
        if (!setting.help.isEmpty()) {
            TextView help = text(setting.help, 13, RealmLauncher.PAPER);
            help.setTypeface(Typeface.MONOSPACE);
            help.setTextIsSelectable(true);
            help.setPadding(0, dp(8), 0, dp(8));
            ScrollView scroll = new ScrollView(this);
            scroll.addView(help);
            body.addView(scroll, new LinearLayout.LayoutParams(-1, dp(Math.min(220, 40 + setting.help.split("\n").length * 18))));
        }
        final Switch toggle;
        final RadioGroup group;
        final EditText field;
        if (setting.kind == ServerConfigFile.Kind.SWITCH) {
            toggle = new Switch(this);
            toggle.setText("On");
            toggle.setTextColor(RealmLauncher.PAPER);
            toggle.setChecked(ServerConfigFile.Setting.switchedOn(current));
            body.addView(toggle);
            group = null; field = null;
        } else {
            toggle = null;
            field = new EditText(this);
            field.setTextColor(Color.WHITE);
            field.setSingleLine(true);
            field.setText(current);
            switch (setting.kind) {
                case INTEGER: case CHOICE:
                    field.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_SIGNED |
                        (setting.kind == ServerConfigFile.Kind.CHOICE ? InputType.TYPE_NUMBER_FLAG_DECIMAL : 0));
                    break;
                case DECIMAL:
                    field.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_SIGNED | InputType.TYPE_NUMBER_FLAG_DECIMAL);
                    break;
                default:
                    field.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
            }
            if (setting.kind == ServerConfigFile.Kind.CHOICE) {
                group = new RadioGroup(this);
                for (int i = 0; i < setting.choices.size(); i++) {
                    ServerConfigFile.Choice choice = setting.choices.get(i);
                    RadioButton option = new RadioButton(this);
                    option.setId(View.generateViewId());
                    option.setText(choice.value + " · " + choice.label);
                    option.setTextColor(RealmLauncher.PAPER);
                    option.setTag(choice.value);
                    group.addView(option);
                    if (choice.value.equals(current)) group.check(option.getId());
                }
                group.setOnCheckedChangeListener((radio, checked) -> {
                    View option = radio.findViewById(checked);
                    if (option != null && option.getTag() != null) field.setText((String) option.getTag());
                });
                body.addView(group);
                body.addView(text("Or enter another value:", 13, MUTED));
            } else group = null;
            body.addView(field);
        }
        TextView error = text("", 13, WARN);
        body.addView(error);
        ScrollView content = new ScrollView(this);
        content.addView(body);
        AlertDialog dialog = new AlertDialog.Builder(this, R.style.RealmDialog).setTitle(setting.key).setView(content)
            .setPositiveButton("Save", null).setNeutralButton("Use default", null).setNegativeButton("Cancel", null).create();
        dialog.setOnShowListener(shown -> {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
                String value = toggle != null ? setting.switchValue(toggle.isChecked()) : field.getText().toString();
                try {
                    overrides.set(setting, value, rules);
                    if (save()) dialog.dismiss(); else error.setText("The change could not be saved on this device.");
                } catch (IllegalArgumentException refused) {
                    error.setText(refused.getMessage());
                }
            });
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(view -> {
                overrides.remove(setting.file, setting.key);
                if (save()) dialog.dismiss(); else error.setText("The change could not be saved on this device.");
            });
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setEnabled(mine != null);
        });
        dialog.show();
    }

    private boolean save() {
        try { overrides.write(ServerSettingsStore.saved(this)); }
        catch (IOException failed) {
            try { overrides = ServerSettingsStore.overrides(this); } catch (IOException ignored) { /* Keep the in-memory view. */ }
            refresh();
            return false;
        }
        refresh();
        return true;
    }

    private void confirmResetAll() {
        new AlertDialog.Builder(this, R.style.RealmDialog).setTitle("Reset all changes?")
            .setMessage("Every server setting returns to Esteria's default at the next start.")
            .setPositiveButton("Reset", (dialog, which) -> { overrides.clear(); save(); })
            .setNegativeButton("Cancel", null).show();
    }

    private final class RowAdapter extends BaseAdapter {
        @Override public int getCount() { return rows.size(); }
        @Override public Object getItem(int position) { return rows.get(position); }
        @Override public long getItemId(int position) { return position; }
        @Override public int getViewTypeCount() { return 2; }
        @Override public int getItemViewType(int position) { return rows.get(position) instanceof String ? 0 : 1; }
        @Override public boolean isEnabled(int position) { return !(rows.get(position) instanceof String); }
        @Override public View getView(int position, View convert, ViewGroup parent) {
            Object row = rows.get(position);
            if (row instanceof String) {
                TextView heading = convert instanceof TextView ? (TextView) convert : text("", 14, RealmLauncher.GOLD);
                heading.setText((String) row);
                heading.setTypeface(Typeface.DEFAULT_BOLD);
                heading.setPadding(dp(12), dp(14), dp(12), dp(4));
                heading.setBackgroundColor(0xff0e1512);
                return heading;
            }
            ServerConfigFile.Setting setting = (ServerConfigFile.Setting) row;
            LinearLayout item = convert instanceof LinearLayout ? (LinearLayout) convert : settingRow();
            TextView name = (TextView) item.getChildAt(0), value = (TextView) item.getChildAt(1);
            name.setText(setting.key);
            boolean managed = rules.managed(setting.key), changed = overrides.get(setting.file, setting.key) != null;
            name.setTextColor(managed ? MUTED : RealmLauncher.PAPER);
            value.setText(detail(setting));
            value.setTextColor(managed ? MUTED : changed ? RealmLauncher.GOLD : 0xffc4cbbf);
            return item;
        }
        private LinearLayout settingRow() {
            LinearLayout item = new LinearLayout(ServerSettingsActivity.this);
            item.setOrientation(LinearLayout.VERTICAL);
            item.setPadding(dp(12), dp(8), dp(12), dp(8));
            TextView name = text("", 15, RealmLauncher.PAPER);
            name.setTypeface(Typeface.DEFAULT_BOLD);
            item.addView(name);
            TextView value = text("", 13, MUTED);
            value.setMaxLines(2);
            item.addView(value);
            return item;
        }
    }

    private TextView text(String value, int size, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        return view;
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
}
