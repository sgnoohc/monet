package com.phchang.switchboard;

import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import android.util.Base64;
import android.webkit.MimeTypeMap;
import androidx.core.content.FileProvider;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.File;
import java.io.FileOutputStream;

// Opens a downloaded attachment in the phone's own viewer (PDF viewer, video
// player, Photos, Docs, ...). The file is written to the app's cache, which
// the FileProvider in AndroidManifest.xml shares read-only with that app.
@CapacitorPlugin(name = "FileViewer")
public class FileViewerPlugin extends Plugin {

    @PluginMethod
    public void open(PluginCall call) {
        String data = call.getString("data");
        String name = call.getString("name", "file").replaceAll("[/\\\\:]", "_");
        if (name.isEmpty()) name = "file";
        String type = call.getString("type", "");
        if (data == null) {
            call.reject("Nothing to open");
            return;
        }
        try {
            // Keep only the file being opened, so the cache doesn't grow.
            File dir = new File(getContext().getCacheDir(), "opened");
            File[] old = dir.listFiles();
            if (old != null) for (File f : old) f.delete();
            dir.mkdirs();
            File file = new File(dir, name);
            try (FileOutputStream out = new FileOutputStream(file)) {
                out.write(Base64.decode(data, Base64.DEFAULT));
            }

            if (type == null || type.isEmpty() || type.equals("application/octet-stream")) {
                int dot = name.lastIndexOf('.');
                String guess = dot >= 0 ? MimeTypeMap.getSingleton().getMimeTypeFromExtension(name.substring(dot + 1).toLowerCase()) : null;
                type = guess != null ? guess : "*/*";
            }

            Uri uri = FileProvider.getUriForFile(getContext(), getContext().getPackageName() + ".fileprovider", file);
            Intent intent = new Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, type)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            getActivity().startActivity(intent);
            call.resolve();
        } catch (ActivityNotFoundException e) {
            call.reject("No app on this phone can open " + name);
        } catch (Exception e) {
            call.reject("Couldn't open " + name + ": " + e.getMessage());
        }
    }
}
