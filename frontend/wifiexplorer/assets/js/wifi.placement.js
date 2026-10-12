// Wi-Fi Explorer floor placement (Super admins only): pick an AP, click its position on the plan. The position is
// stored as configuration by wifiexplorer.placement.update, keyed by the AP's opaque ID, then the page reloads.
(function () {
    'use strict';

    function init() {
        var panel = document.querySelector('.we-placement');
        var svg = document.querySelector('svg.we-floor');
        if (!panel || !svg) {
            return;
        }
        var select = document.getElementById('we-place-ap');
        var status = document.getElementById('we-place-status');
        var remove = document.getElementById('we-place-remove');
        var aspect = parseFloat(svg.getAttribute('data-aspect')) || 0.6;

        function send(fields) {
            var body = new URLSearchParams();
            body.append('_csrf_token', panel.getAttribute('data-token'));
            Object.keys(fields).forEach(function (key) { body.append(key, fields[key]); });
            status.textContent = 'Saving…';
            return fetch('zabbix.php?action=' + encodeURIComponent(panel.getAttribute('data-action')), {
                method: 'POST', credentials: 'same-origin', body: body,
                headers: {'Content-Type': 'application/x-www-form-urlencoded'}
            }).then(function (response) { return response.json(); }).then(function (result) {
                if (result && result.ok) {
                    var url = new URL(window.location.href);
                    url.searchParams.set('ap', fields.ap_uid);
                    window.location.assign(url.toString());
                    return;
                }
                status.textContent = (result && result.error) || 'The placement was not saved.';
            }).catch(function () {
                status.textContent = 'The placement was not saved.';
            });
        }

        svg.classList.add('we-floor-placing');
        svg.addEventListener('click', function (event) {
            var apUid = select ? select.value : '';
            if (!apUid) {
                status.textContent = 'Select an AP first.';
                return;
            }
            event.preventDefault();
            var point = svg.createSVGPoint();
            point.x = event.clientX;
            point.y = event.clientY;
            var local = point.matrixTransform(svg.getScreenCTM().inverse());
            var x = Math.min(1, Math.max(0, local.x / 1000));
            var y = Math.min(1, Math.max(0, local.y / (1000 * aspect)));
            send({ap_uid: apUid, floor_id: panel.getAttribute('data-floor'), x: x.toFixed(4), y: y.toFixed(4)});
        });
        if (remove) {
            remove.addEventListener('click', function () {
                var apUid = select ? select.value : '';
                if (apUid) {
                    send({ap_uid: apUid, remove: '1'});
                }
                else {
                    status.textContent = 'Select an AP first.';
                }
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    }
    else {
        init();
    }
}());
