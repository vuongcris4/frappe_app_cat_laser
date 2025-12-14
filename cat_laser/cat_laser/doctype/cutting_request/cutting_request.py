# frappe-bench/apps/cat_laser/cat_laser/cat_laser/doctype/cutting_request/cutting_request.py
import frappe
from frappe.model.document import Document
from frappe.utils.background_jobs import enqueue
import json

# Import Class tối ưu hóa
from cat_laser.utils.optimization import SteelCuttingOptimizer

class CuttingRequest(Document):
    pass

@frappe.whitelist()
def run_optimization_job(doc_name):
    """Hàm nhận request từ JS"""
    
    # 1. Cập nhật trạng thái Processing
    doc = frappe.get_doc("Cutting Request", doc_name)
    if doc.status != 'Processing':
        doc.status = 'Processing'
        doc.save(ignore_permissions=True)
        frappe.db.commit() 
    
    # 2. Đẩy vào Background Job
    # Lưu ý: user_to_notify=None để báo hiệu cho hàm bên dưới là Broadcast
    enqueue(
        method=execute_optimization,
        queue='default', 
        timeout=3000, 
        doc_name=doc_name
    )
    return "Job started"

def execute_optimization(doc_name):
    """Hàm chạy thực tế trong background worker"""
    
    # === SỬA QUAN TRỌNG: user=None để Gửi cho TẤT CẢ (Broadcast) ===
    def log(msg):
        frappe.publish_realtime('cutting_log', {'message': msg}, user=None)

    log('⏳ Worker bắt đầu nhận việc...')
    
    try:
        doc = frappe.get_doc("Cutting Request", doc_name)

        # 1. Chuẩn bị dữ liệu
        piece_names = []
        segment_sizes = []
        demands = []
        
        valid_items = [row for row in doc.items if row.length > 0 and row.qty > 0]
        
        if not valid_items:
            log('❌ Không có dữ liệu kích thước hợp lệ.')
            doc.status = "Draft"
            doc.save(ignore_permissions=True)
            return

        for row in valid_items:
            piece_names.append(row.item_name)
            segment_sizes.append(float(row.length))
            demands.append(int(row.qty))

        # 2. Khởi tạo bộ tối ưu hóa
        # Truyền user_to_notify=None vào đây luôn
        optimizer = SteelCuttingOptimizer(
            length=doc.stock_length,
            te_dau_sat=10,
            piece_names=piece_names,
            segment_sizes=segment_sizes,
            demands=demands,
            blade_width=4,
            factors=[1, 2, 3, 4, 5, 6, 8, 10],
            max_manual_cuts=0,
            max_stock_over=doc.max_surplus,
            time_limit_seconds=doc.time_limit,
            user_to_notify=None # <--- QUAN TRỌNG: None để Broadcast
        )

        # 3. Chạy Phase 1
        log('🚀 Phase 1: Đang tìm patterns...')
        optimizer.optimize_cutting()

        # 4. Chạy Phase 2
        log('⚙️ Phase 2: Đang tối ưu phân phối...')
        optimizer.optimize_distribution() 

        # 5. Cập nhật trạng thái thành công
        doc.reload() 
        doc.status = "Completed"
        
        # Lưu kết quả HTML vào field (lấy từ biến tạm hoặc logic tạo HTML nếu cần)
        # Ở đây ta giả định optimization.py đã in log HTML, 
        # nhưng nếu muốn lưu vào DocType, bạn nên sửa optimization.py để trả về HTML string.
        # Tạm thời gán thông báo thành công:
        doc.result_html = f"""
            <div class="alert alert-success">
                <h4>✅ Tính toán hoàn tất!</h4>
                <p>Kết quả chi tiết đã được hiển thị qua Log Realtime (Vui lòng xem lại Console/Log).</p>
            </div>
        """
        doc.save(ignore_permissions=True)
        
        # Báo hiệu kết thúc (Broadcast)
        frappe.publish_realtime('cutting_finish', {'doc_name': doc.name}, user=None)

    except Exception as e:
        frappe.db.rollback()
        error_msg = f"Lỗi tính toán: {str(e)}"
        frappe.log_error(error_msg, "Cutting Optimization Error")
        
        # Gửi log lỗi
        log(f'❌ {error_msg}')
        
        # Revert trạng thái
        doc = frappe.get_doc("Cutting Request", doc_name)
        doc.status = "Draft"
        doc.save(ignore_permissions=True)
        frappe.db.commit()


