using Toybox.ActivityMonitor;
using Toybox.Application;
using Toybox.Graphics;
using Toybox.SensorHistory;
using Toybox.System;
using Toybox.WatchUi;

class A2zView extends WatchUi.View {

    function initialize() {
        View.initialize();
    }

    function onUpdate(dc) {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        var w = dc.getWidth();
        var h = dc.getHeight();

        dc.drawText(w / 2, 20, Graphics.FONT_SMALL,
            "a2zbridge", Graphics.TEXT_JUSTIFY_CENTER);

        var hr = _latestHr();
        var info = ActivityMonitor.getInfo();

        dc.drawText(w / 2, 55, Graphics.FONT_LARGE,
            hr == null ? "--" : hr.toString() + " bpm",
            Graphics.TEXT_JUSTIFY_CENTER);

        dc.drawText(w / 2, 100, Graphics.FONT_TINY,
            "steps " + (info.steps == null ? "--" : info.steps.toString()),
            Graphics.TEXT_JUSTIFY_CENTER);

        var url = Application.Properties.getValue("ingest_url");
        dc.drawText(w / 2, h - 25, Graphics.FONT_XTINY,
            url == null || url.length() == 0 ? "no ingest_url set" : "posting ok",
            Graphics.TEXT_JUSTIFY_CENTER);
    }

    hidden function _latestHr() {
        var iter = SensorHistory has :getHeartRateHistory
            ? SensorHistory.getHeartRateHistory({})
            : null;
        if (iter == null) { return null; }
        var sample = iter.next();
        return sample == null ? null : sample.data;
    }
}

class A2zDelegate extends WatchUi.BehaviorDelegate {
    function initialize() {
        BehaviorDelegate.initialize();
    }

    function onSelect() {
        // Manual push button, handy for debugging.
        Reporter.send(null);
        return true;
    }
}
