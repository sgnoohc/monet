package com.phchang.switchboard;

import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

// Makes all of Switchboard's text bigger or smaller (Settings → Appearance → Size).
@CapacitorPlugin(name = "Display")
public class DisplayPlugin extends Plugin {

    @PluginMethod
    public void setTextZoom(PluginCall call) {
        int percent = Math.max(50, Math.min(250, call.getInt("percent", 100)));
        getActivity().runOnUiThread(() -> {
            getBridge().getWebView().getSettings().setTextZoom(percent);
            call.resolve();
        });
    }
}
