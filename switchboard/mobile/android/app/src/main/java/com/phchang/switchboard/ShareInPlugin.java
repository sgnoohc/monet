package com.phchang.switchboard;

import android.content.ContentResolver;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.provider.OpenableColumns;
import android.util.Log;
import android.webkit.MimeTypeMap;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;

// Receives pictures, files and text shared to Switchboard from other apps
// (a screenshot from Photos, a PDF from Files, a link from the browser). Shared
// files are copied into the app's cache; the page loads them from there, lets
// you pick a chat, and puts them in the composer.
@CapacitorPlugin(name = "ShareIn")
public class ShareInPlugin extends Plugin {
    private static final long MAX_BYTES = 50L * 1024 * 1024;
    private JSObject pending;
    private String lastShare = "";
    private long lastShareAt = 0;

    @Override
    public void load() {
        receive(getActivity().getIntent());
    }

    @Override
    protected void handleOnNewIntent(Intent intent) {
        super.handleOnNewIntent(intent);
        receive(intent);
    }

    // The page asks for what was shared (at start, and after each "shared" event).
    @PluginMethod
    public void take(PluginCall call) {
        JSObject share;
        synchronized (this) {
            share = pending;
            pending = null;
        }
        call.resolve(share != null ? share : new JSObject());
    }

    private void receive(Intent intent) {
        if (intent == null) return;
        String action = intent.getAction();
        if (!Intent.ACTION_SEND.equals(action) && !Intent.ACTION_SEND_MULTIPLE.equals(action)) return;
        Log.i("ShareIn", "received " + action + " " + intent.getType());
        intent.setAction(Intent.ACTION_MAIN); // handled; don't take it again if the app is recreated

        ArrayList<Uri> uris = new ArrayList<>();
        if (Intent.ACTION_SEND.equals(action)) {
            Uri uri = Build.VERSION.SDK_INT >= 33
                ? intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri.class)
                : intent.getParcelableExtra(Intent.EXTRA_STREAM);
            if (uri != null) uris.add(uri);
        } else {
            ArrayList<Uri> list = Build.VERSION.SDK_INT >= 33
                ? intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri.class)
                : intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (list != null) uris.addAll(list);
        }
        String text = intent.getStringExtra(Intent.EXTRA_TEXT);
        String type = intent.getType();
        // On a cold start the same share can arrive twice (at load and as a new intent).
        String id = uris + "|" + text;
        long now = System.currentTimeMillis();
        if (id.equals(lastShare) && now - lastShareAt < 5000) return;
        lastShare = id;
        lastShareAt = now;

        // Copying can take a moment for videos, so it happens off the main thread.
        new Thread(() -> {
            JSArray files = new JSArray();
            int tooLarge = 0;
            int failed = 0;
            File dir = new File(getContext().getCacheDir(), "shared");
            File[] old = dir.listFiles();
            if (old != null) for (File f : old) f.delete();
            dir.mkdirs();
            int i = 0;
            for (Uri uri : uris) {
                JSObject f = copy(uri, dir, i++, type);
                if (f == null) failed++;
                else if (f.has("tooLarge")) tooLarge++;
                else files.put(f);
            }
            JSObject share = new JSObject();
            share.put("files", files);
            if (text != null) share.put("text", text);
            share.put("tooLarge", tooLarge);
            share.put("failed", failed);
            synchronized (this) {
                pending = share;
            }
            notifyListeners("shared", new JSObject(), true);
        }).start();
    }

    private static JSObject tooLarge() {
        JSObject f = new JSObject();
        f.put("tooLarge", true);
        return f;
    }

    private JSObject copy(Uri uri, File dir, int index, String fallbackType) {
        ContentResolver resolver = getContext().getContentResolver();
        String name = null;
        long size = -1;
        try (Cursor c = resolver.query(uri, null, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                int n = c.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                int s = c.getColumnIndex(OpenableColumns.SIZE);
                if (n >= 0) name = c.getString(n);
                if (s >= 0 && !c.isNull(s)) size = c.getLong(s);
            }
        } catch (Exception ignored) {
        }
        if (size > MAX_BYTES) return tooLarge();
        String type = resolver.getType(uri);
        if (type == null) type = fallbackType != null && !fallbackType.contains("*") ? fallbackType : "application/octet-stream";
        if (name == null || name.isEmpty()) {
            String ext = MimeTypeMap.getSingleton().getExtensionFromMimeType(type);
            name = "shared-" + (index + 1) + (ext != null ? "." + ext : "");
        }
        name = name.replaceAll("[/\\\\:]", "_");
        File out = new File(dir, index + "-" + name); // index: two shared files may have the same name
        try (InputStream in = resolver.openInputStream(uri); OutputStream os = new FileOutputStream(out)) {
            if (in == null) return null;
            byte[] buf = new byte[64 * 1024];
            long total = 0;
            int r;
            while ((r = in.read(buf)) > 0) {
                total += r;
                if (total > MAX_BYTES) {
                    os.close();
                    out.delete();
                    return tooLarge();
                }
                os.write(buf, 0, r);
            }
        } catch (Exception e) {
            Log.w("ShareIn", "couldn't read " + uri, e);
            out.delete();
            return null;
        }
        JSObject f = new JSObject();
        f.put("path", out.getAbsolutePath());
        f.put("name", name);
        f.put("type", type);
        return f;
    }
}
