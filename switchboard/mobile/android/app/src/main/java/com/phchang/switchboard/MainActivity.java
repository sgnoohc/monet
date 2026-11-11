package com.phchang.switchboard;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(FileViewerPlugin.class); // before super, so the page can use it at once
        super.onCreate(savedInstanceState);
    }
}
