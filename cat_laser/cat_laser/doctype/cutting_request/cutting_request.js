// frappe-bench/apps/cat_laser/cat_laser/cat_laser/doctype/cutting_request/cutting_request.js
frappe.ui.form.on('Cutting Request', {
    refresh: function (frm) {
        // 1. Lắng nghe log realtime (Hiển thị Alert xanh + Console log)
        frappe.realtime.on('cutting_log', function (data) {
            frappe.show_alert({ message: data.message, indicator: 'blue' });
            console.log("🔥 LOG TỪ SERVER:", data.message);
        });

        // 2. Lắng nghe sự kiện hoàn thành
        frappe.realtime.on('cutting_finish', function (data) {
            if (data.doc_name === frm.doc.name) {
                frappe.msgprint("✅ Đã tính toán xong!");
                frm.reload_doc();
            }
        });
    },

    run_optimization: function (frm) {
        // Hàm gọi server
        const trigger_job = () => {
            frappe.call({
                method: 'cat_laser.cat_laser.doctype.cutting_request.cutting_request.run_optimization_job',
                args: {
                    doc_name: frm.doc.name
                },
                freeze: true, // Khóa màn hình
                freeze_message: "🚀 Đang gửi lệnh chạy ngầm...",
                callback: function (r) {
                    frappe.msgprint("Đã gửi lệnh! Hãy để ý thông báo góc phải màn hình.");
                    frm.reload_doc(); // Tải lại để thấy trạng thái Processing
                }
            });
        };

        // Logic: Lưu trước khi chạy nếu có thay đổi
        if (frm.is_dirty()) {
            frm.save().then(() => {
                trigger_job();
            });
        } else {
            trigger_job();
        }
    }
});


