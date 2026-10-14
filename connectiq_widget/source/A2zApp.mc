using Toybox.Application;
using Toybox.Background;
using Toybox.System;
using Toybox.Time;
using Toybox.WatchUi;

// Interval between background pushes. 5 min = 300s is the Connect IQ minimum.
const BG_INTERVAL_SEC = 300;

class A2zApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state) {
        _scheduleBackground();
    }

    function onStop(state) {
        // Keep the temporal event alive across widget exits — that's the
        // whole point. Nothing to do here.
    }

    function getInitialView() {
        return [ new A2zView(), new A2zDelegate() ];
    }

    // Called by the OS when the widget's settings change.
    function onSettingsChanged() {
        WatchUi.requestUpdate();
    }

    // Returns the delegate the OS uses to run the background task.
    function getServiceDelegate() {
        return [ new A2zServiceDelegate() ];
    }

    hidden function _scheduleBackground() {
        var current = Background.getTemporalEventRegisteredTime();
        if (current == null) {
            try {
                Background.registerForTemporalEvent(new Time.Duration(BG_INTERVAL_SEC));
            } catch (ex instanceof Background.InvalidBackgroundTimeException) {
                System.println("Background interval rejected: " + ex.getErrorMessage());
            }
        }
    }
}

// Runs out-of-process; cannot touch UI, cannot block.
class A2zServiceDelegate extends System.ServiceDelegate {

    function initialize() {
        ServiceDelegate.initialize();
    }

    function onTemporalEvent() {
        Reporter.send(method(:_onReportResult));
    }

    function _onReportResult(responseCode, data) {
        // Exit the background slot. The OS re-wakes us at the next tick
        // because the temporal event is still registered.
        Background.exit(null);
    }
}
