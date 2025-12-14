// cat_laser/cat_laser/doctype/realtime_counter/realtime_counter.js

frappe.ui.form.on('Realtime Counter', {
    refresh(frm) {
        // Thêm nút Start / Stop chỉ 1 lần
        if (!frm.is_new() && !frm._counter_buttons_added) {
            frm._counter_buttons_added = true;

            // Nút Start Counter
            frm.add_custom_button(__('Start Counter'), () => {
                frappe.call({
                    method: 'cat_laser.cat_laser.doctype.realtime_counter.realtime_counter.start_counter',
                    args: {
                        docname: frm.doc.name,
                    },
                    freeze: true,
                    freeze_message: __('Đang bắt đầu tiến trình đếm...'),
                    callback(r) {
                        frappe.msgprint(__('Đã start tiến trình đếm.'));
                    }
                });
            });

            // Nút Stop Counter
            frm.add_custom_button(__('Stop Counter'), () => {
                frappe.call({
                    method: 'cat_laser.cat_laser.doctype.realtime_counter.realtime_counter.stop_counter',
                    args: {
                        docname: frm.doc.name,
                    },
                    freeze: true,
                    freeze_message: __('Đang gửi yêu cầu dừng...'),
                    callback(r) {
                        frappe.msgprint(__('Đã gửi yêu cầu dừng tiến trình.'));
                    }
                });
            });
        }

        // Lắng nghe realtime chỉ 1 lần
        if (!frm._counter_listener_added) {
            frm._counter_listener_added = true;

            frappe.realtime.on('realtime_counter_update', (data) => {
                // Chỉ handle đúng document đang mở
                if (data.docname !== frm.doc.name) return;

                const value = data.value;

                // Update field counter trên UI
                frm.set_value('counter', value);

                // Hiển thị trên dashboard
                frm.dashboard.set_headline_alert(
                    __('Đang đếm: {0}', [value]),
                    'blue'
                );

                console.log('Realtime Counter', frm.doc.name, '→', value);
            });
        }
    }
});
