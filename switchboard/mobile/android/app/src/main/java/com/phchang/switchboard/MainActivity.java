package com.phchang.switchboard;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        // Before super, so the page can use them at once
        registerPlugin(FileViewerPlugin.class);
        registerPlugin(ShareInPlugin.class);
        registerPlugin(DisplayPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
