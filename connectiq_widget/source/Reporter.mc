using Toybox.ActivityMonitor;
using Toybox.Application;
using Toybox.Background;
using Toybox.Communications;
using Toybox.SensorHistory;
using Toybox.System;
using Toybox.Time;
using Toybox.Time.Gregorian;

// Sends one snapshot (HR history + current stress + body battery + steps)
// to the ingest URL configured in app settings.
module Reporter {

    // 5 minutes of HR history per push, matching the background interval.
    const HR_WINDOW_SEC = 300;

    (:background)
    function send(callback) {
        var url = Application.Properties.getValue("ingest_url");
        var token = Application.Properties.getValue("ingest_token");
        if (url == null || url.length() == 0 || token == null || token.length() == 0) {
            if (callback != null) { callback.invoke(-1, null); }
            return;
        }

        var payload = _collect();
        var options = {
            :method => Communications.HTTP_REQUEST_METHOD_POST,
            :headers => {
                "Content-Type" => Communications.REQUEST_CONTENT_TYPE_JSON,
                "Authorization" => "Bearer " + token
            },
            :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
        };

        Communications.makeWebRequest(url, payload, options, callback);
    }

    hidden function _collect() {
        var now = Time.now();
        var payload = {
            "device_id" => _deviceId(),
            "ts" => _iso8601(now),
            "watch" => {
                "battery_pct" => System.getSystemStats().battery
            },
            "samples" => {}
        };

        payload["samples"]["hr"] = _hrSamples(now);
        payload["samples"]["stress"] = _latest(SensorHistory, :getStressHistory);
        payload["samples"]["body_battery"] = _latest(SensorHistory, :getBodyBatteryHistory);

        var info = ActivityMonitor.getInfo();
        payload["samples"]["steps_today"] = info == null ? null : info.steps;
        payload["samples"]["calories_today"] = info == null ? null : info.calories;

        return payload;
    }

    // Device-unique opaque string. Reset on factory reset.
    hidden function _deviceId() {
        if (System has :getDeviceSettings) {
            var ds = System.getDeviceSettings();
            if (ds has :uniqueIdentifier && ds.uniqueIdentifier != null) {
                return ds.uniqueIdentifier;
            }
        }
        return "unknown-fenix";
    }

    hidden function _hrSamples(now) {
        if (!(SensorHistory has :getHeartRateHistory)) { return []; }
        var iter = SensorHistory.getHeartRateHistory({
            :period => new Time.Duration(HR_WINDOW_SEC),
            :order => SensorHistory.ORDER_OLDEST_FIRST
        });
        var out = [];
        var sample = iter.next();
        while (sample != null && out.size() < 60) {
            if (sample.data != null) {
                out.add({
                    "ts" => _iso8601(sample.when),
                    "bpm" => sample.data
                });
            }
            sample = iter.next();
        }
        return out;
    }

    // Grab the newest sample from any `SensorHistory.get<X>History` method
    // that this device happens to expose.
    hidden function _latest(mod, sym) {
        if (!(mod has sym)) { return null; }
        var iter = mod.method(sym).invoke({});
        if (iter == null) { return null; }
        var sample = iter.next();
        return sample == null ? null : sample.data;
    }

    hidden function _iso8601(moment) {
        var info = Gregorian.utcInfo(moment, Time.FORMAT_SHORT);
        return info.year.format("%04d") + "-" +
               info.month.format("%02d") + "-" +
               info.day.format("%02d") + "T" +
               info.hour.format("%02d") + ":" +
               info.min.format("%02d") + ":" +
               info.sec.format("%02d") + "Z";
    }
}
