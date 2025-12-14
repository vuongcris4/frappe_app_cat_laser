# cat_laser/cat_laser/doctype/realtime_counter/realtime_counter.py

import time
import frappe
from frappe.model.document import Document


class RealtimeCounter(Document):
    pass


@frappe.whitelist()
def start_counter(docname: str):
    """
    API được gọi từ frontend để bắt đầu quá trình đếm.
    Đọc start, end, interval từ document.
    """
    doc = frappe.get_doc("Realtime Counter", docname)

    # Validate đơn giản
    if doc.interval_seconds and doc.interval_seconds <= 0:
        frappe.throw("Interval (seconds) phải > 0")

    if doc.start_value is None or doc.end_value is None:
        frappe.throw("Bạn phải nhập cả Start Value và End Value")

    # Reset cờ stop mỗi lần start lại
    frappe.db.set_value(
        "Realtime Counter",
        docname,
        "stop_requested",
        0,
        update_modified=False,
    )
    frappe.db.commit()

    # Đưa vào hàng đợi long
    frappe.enqueue(
        "cat_laser.cat_laser.doctype.realtime_counter.realtime_counter.run_counter",
        docname=docname,
        queue="long",
        job_name=f"realtime_counter_{docname}",
    )


@frappe.whitelist()
def stop_counter(docname: str):
    """
    Được gọi từ nút Stop trên UI.
    Đặt cờ stop_requested = 1 để vòng lặp trong background job tự dừng.
    """
    frappe.db.set_value(
        "Realtime Counter",
        docname,
        "stop_requested",
        1,
        update_modified=False,
    )
    frappe.db.commit()

    # (optional) Gửi realtime báo trạng thái hiện tại
    current_value = frappe.db.get_value("Realtime Counter", docname, "counter")

    frappe.publish_realtime(
        event="realtime_counter_update",
        message={
            "docname": docname,
            "value": current_value,
        },
        doctype="Realtime Counter",
        docname=docname,
    )


def run_counter(docname: str):
    """
    Background job: đếm từ start_value → end_value, mỗi interval giây.
    Có thể dừng giữa chừng bằng cách set stop_requested = 1.
    """
    doc = frappe.get_doc("Realtime Counter", docname)

    start = int(doc.start_value)
    end = int(doc.end_value)
    interval = int(doc.interval_seconds or 1)

    if interval <= 0:
        interval = 1

    # Nếu end < start thì đếm lùi
    step = 1 if end >= start else -1
    current = start

    while True:
        # Cập nhật DB để lưu lại
        frappe.db.set_value(
            "Realtime Counter",
            docname,
            "counter",
            current,
            update_modified=False,
        )
        frappe.db.commit()

        # Gửi realtime NGAY LẬP TỨC (KHÔNG after_commit)
        frappe.publish_realtime(
            event="realtime_counter_update",
            message={
                "docname": docname,
                "value": current,
            },
            doctype="Realtime Counter",
            docname=docname,
        )

        # Check cờ stop
        stop_flag = frappe.db.get_value(
            "Realtime Counter",
            docname,
            "stop_requested",
        )
        if stop_flag:
            break

        # Điều kiện dừng khi tới end
        if current == end:
            break

        current += step
        time.sleep(interval)
