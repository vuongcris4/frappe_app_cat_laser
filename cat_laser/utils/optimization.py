# frappe-bench/apps/cat_laser/cat_laser/utils/optimization.py
import os
import json
import pickle
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd  
from collections import Counter
import time
import threading
from datetime import datetime
import frappe

# OR-Tools CP-SAT
from ortools.sat.python import cp_model


# ===================================================================
# Lớp Timer (Sửa để Broadcast user=None)
# ===================================================================
class SolverTimer(threading.Thread):
    def __init__(self, total_time, user_to_notify):
        super().__init__()
        self.total_time = total_time
        self.user_to_notify = user_to_notify
        self.stop_event = threading.Event()
        self.start_time = None
        self.daemon = True

    def run(self):
        self.start_time = time.time()
        while not self.stop_event.is_set():
            elapsed = int(time.time() - self.start_time)
            if elapsed > self.total_time:
                break
            
            # === SỬA: user=None để Broadcast ===
            frappe.publish_realtime(
                "cutting_log", 
                {'message': f"⏳ Đang chạy: {elapsed}/{int(self.total_time)}s"}, 
                user=None 
            )
            time.sleep(1)

    def stop(self):
        self.stop_event.set()


# =========================================================
# GIAI ĐOẠN 1: Thu thập nghiệm
# =========================================================
class SolutionAndLogCollector(cp_model.CpSolverSolutionCallback):
    def __init__(
        self,
        vars_x,
        seg_scaled,
        blade_scaled,
        scale,
        length,
        te_dau_sat,
        exclude_set,
        user_to_notify,
        accept_at_most=1000,
        print_every=100,
    ):
        super().__init__()
        self._vars_x = vars_x
        self._seg_scaled = seg_scaled
        self._blade_scaled = blade_scaled
        self._scale = scale
        self._length = length
        self._te = te_dau_sat
        self._exclude = exclude_set 
        self._user_to_notify = user_to_notify
        self._seen = set()
        self._solutions = [] 
        self._accept_at_most = accept_at_most
        self._print_every = max(1, print_every)
        self._cnt = 0
        self._start = time.time()

    def on_solution_callback(self):
        x = [int(self.Value(v)) for v in self._vars_x]
        key = tuple(x)

        if key in self._seen or key in self._exclude:
            return

        sum_x = sum(x)
        obj_scaled = sum(self._seg_scaled[i] * x[i] for i in range(len(x))) + self._blade_scaled * sum_x
        obj_value = obj_scaled / self._scale

        self._solutions.append((obj_value, x))
        self._seen.add(key)

        self._cnt += 1
        if self._cnt % self._print_every == 0:
            hao_hut = self._length - obj_value
            # === SỬA: user=None để Broadcast ===
            frappe.publish_realtime(
                'cutting_log',
                {'message': f"👉 Tìm thấy pattern {self._cnt}: Hao hụt {hao_hut}mm"},
                user=None
            )

        if len(self._solutions) >= self._accept_at_most:
            self.StopSearch()

    @property
    def solutions(self):
        return sorted(self._solutions, key=lambda t: t[0], reverse=True)


# ===================================================================
# Lớp Tối Ưu Hóa Chính
# ===================================================================
class SteelCuttingOptimizer:
    def __init__(
        self,
        length,
        te_dau_sat,
        piece_names,
        segment_sizes,
        demands,
        blade_width,
        factors,
        max_manual_cuts,
        max_stock_over,
        time_limit_seconds=30.0,
        user_to_notify=None # Mặc định None
    ):
        self.length = length
        self.te_dau_sat = te_dau_sat
        self.piece_names = piece_names
        self.segment_sizes = np.array(segment_sizes)
        self.demands = np.array(demands)
        self.blade_width = blade_width
        self.factors = sorted(list(set(factors)), reverse=True) + [1, 0]
        self.max_manual_cuts = max_manual_cuts
        self.max_stock_over = max_stock_over
        self.time_limit_seconds = time_limit_seconds
        
        self.user_to_notify = user_to_notify 

        self.solutions = []
        self.solution_matrix = None

        self.BASE_DIR = Path(__file__).resolve().parents[1]
        self.CACHE_DIR = self.BASE_DIR / "pattern_cache"
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # --- Helper Log nội bộ (Quan trọng nhất) ---
    def log(self, message):
        # === SỬA: user=None để Broadcast ===
        frappe.publish_realtime('cutting_log', {'message': message}, user=None)

    def _cache_key(self):
        payload = {
            "length": int(self.length),
            "segment_sizes": list(map(float, self.segment_sizes.tolist())),
            "blade_width": float(self.blade_width),
        }
        s = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(s.encode("utf-8")).hexdigest()

    def _cache_path(self):
        key = self._cache_key()
        return self.CACHE_DIR / f"patterns_{key}.pkl"

    def save_solution_to_pickle(self):
        path = self._cache_path()
        tmp = str(path) + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump(self.solutions, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)

    def cut_list(self, lst, x, length):
        for i, (obj_value, solution) in enumerate(lst):
            if obj_value + x <= length:
                return lst[i:]
        return []

    def load_solution_from_pickle(self):
        path = self._cache_path()
        if not path.exists():
            return []
        try:
            list_solutions = None
            with open(path, "rb") as f:
                list_solutions = pickle.load(f)
        except Exception:
            return []

        self.log("------------------------------------------------")
        self.log(f"ĐÃ CÓ {len(list_solutions)} NGHIỆM TRONG CACHE")
        self.log("------------------------------------------------")

        list_solutions = self.cut_list(list_solutions, self.te_dau_sat, self.length)

        if len(self.segment_sizes) > 5:
            filtered = [
                (obj_value, solution)
                for obj_value, solution in list_solutions
                if sum(1 for x in solution if x != 0) <= 5
            ]
            return filtered
        else:
            return list_solutions

    def _solve_single_bar_batch(self, max_solutions=1000, time_limit_sec=None):
        self.log(f"Bắt đầu GĐ 1: Tìm các pattern (tối đa {max_solutions:,} phương án). Vui lòng chờ...")
        model = cp_model.CpModel()

        n = len(self.segment_sizes)
        vars_x = [model.NewIntVar(0, 30, f"x_{i}") for i in range(n)]
        sum_x = cp_model.LinearExpr.Sum(vars_x)

        scale = 10
        seg_scaled = [int(round(s * scale)) for s in self.segment_sizes.tolist()]
        blade_scaled = int(round(self.blade_width * scale))
        length_scaled = int(round(self.length * scale))

        objective_scaled = cp_model.LinearExpr.Sum(
            [seg_scaled[i] * vars_x[i] for i in range(n)]
        ) + blade_scaled * sum_x

        lower = int(round(length_scaled * (1 - 0.01)))
        upper = int(round(length_scaled))
        model.Add(objective_scaled >= lower)
        model.Add(objective_scaled <= upper)

        solver = cp_model.CpSolver()
        solver.parameters.enumerate_all_solutions = True
        solver.parameters.log_search_progress = True
        solver.parameters.num_search_workers = 1

        exclude_set = set()
        for _, sol in self.solutions:
            exclude_set.add(tuple(int(v) for v in sol))

        collector = SolutionAndLogCollector(
            vars_x=vars_x,
            seg_scaled=seg_scaled,
            blade_scaled=blade_scaled,
            scale=scale,
            length=self.length,
            te_dau_sat=self.te_dau_sat,
            exclude_set=exclude_set,
            user_to_notify=self.user_to_notify,
            accept_at_most=max_solutions,
            print_every=100,
        )

        solver.SearchForAllSolutions(model, collector)
        self.log(f"GĐ 1: Tìm thấy {len(collector.solutions)} patterns mới.")
        return collector.solutions

    def optimize_cutting(self):
        self.solutions = self.load_solution_from_pickle()

        if not self.solutions:
            self.log("Chưa có nghiệm trong CACHE, đang tìm nghiệm...")
        elif 0 < len(self.solutions) < 10:
            self.log("DANH SÁCH NGHIỆM QUÁ NHỎ, ĐANG GIẢI LẠI!!!!")
            self.solutions = []

        if not self.solutions:
            MAX_SOLUTIONS = 100000
            batch = self._solve_single_bar_batch(
                max_solutions=MAX_SOLUTIONS,
                time_limit_sec=None
            )
            if not batch:
                raise ValueError("Không tìm được nghiệm phù hợp cho 1 cây sắt (GĐ 1).")

            if len(self.segment_sizes) > 5:
                before_count = len(batch)
                batch = [
                    (obj, sol) for obj, sol in batch
                    if sum(1 for x in sol if x > 0) <= 5
                ]
                self.log(f"GĐ 1: Đã lọc bỏ pattern quá 5 loại kích thước: {before_count} -> {len(batch)} patterns.")

            self.log(f"GĐ 1: Còn lại {len(batch)} patterns sau khi lọc.")
            self.solutions = batch
            self.save_solution_to_pickle()

        self.solution_matrix = np.array([sol[1] for sol in self.solutions], dtype=int)
        
        if len(self.solution_matrix) == 0:
             raise ValueError(f"Không tìm được pattern nào phù hợp.")
        
        return self.solutions

    def optimize_distribution(self):
        self.log("<br>Bắt đầu GĐ 2: Đang tính toán bó sắt...<br>")
        if self.solution_matrix is None:
            raise ValueError("Run optimize_cutting first to generate solution matrix.")

        A = self.solution_matrix.T
        L = np.array([self.length - sol[0] for sol in self.solutions], dtype=float)
        m, n = A.shape

        pos_factors = sorted([f for f in self.factors if f > 0], reverse=True)
        idx_one = None
        if 1 in pos_factors:
            idx_one = pos_factors.index(1)

        model = cp_model.CpModel()

        def safe_div_ceil(a, b):
            return (a + b - 1) // b

        UB = []
        for j in range(n):
            caps = []
            for i in range(m):
                aij = int(A[i, j])
                if aij > 0:
                    caps.append(safe_div_ceil(int(self.demands[i]) + int(self.max_stock_over), aij))
            if caps:
                UB.append(min(caps))
            else:
                UB.append(0)

        b = []
        for j in range(n):
            row = []
            for fr in pos_factors:
                ub = safe_div_ceil(UB[j], fr) if UB[j] > 0 else 0
                row.append(model.NewIntVar(0, max(0, ub), f"b_{j}_{fr}"))
            b.append(row)

        def bars_of_pattern(j):
            terms = []
            for r, fr in enumerate(pos_factors):
                if fr != 0:
                    terms.append(fr * b[j][r])
            return sum(terms) if terms else 0

        C = []
        for i in range(m):
            contrib = []
            for j in range(n):
                aij = int(A[i, j])
                if aij != 0:
                    contrib.append(aij * bars_of_pattern(j))
            Ci = model.NewIntVar(0, 10**12, f"C_{i}")
            model.Add(Ci == (sum(contrib) if contrib else 0))
            model.Add(Ci >= int(self.demands[i]))
            model.Add(Ci <= int(self.demands[i]) + int(self.max_stock_over))
            C.append(Ci)

        if idx_one is not None:
            manual_cuts = sum(b[j][idx_one] for j in range(n))
            model.Add(manual_cuts <= int(self.max_manual_cuts))

        loss_terms = []
        bundle_terms = []
        for j in range(n):
            bj = bars_of_pattern(j)
            loss_terms.append(int(round(L[j] * 1000)) * bj)  
            for r in range(len(pos_factors)):
                bundle_terms.append(b[j][r])

        Loss_expr = sum(loss_terms) if loss_terms else 0
        Bundles_expr = sum(bundle_terms) if bundle_terms else 0

        W1 = 10**6
        W2 = 1
        model.Minimize(Loss_expr * W1 + Bundles_expr * W2)

        solver = cp_model.CpSolver()
        solver.parameters.log_search_progress = False
        solver.parameters.max_time_in_seconds = float(self.time_limit_seconds)
        solver.parameters.num_search_workers = 8

        # --- TIMER (Sử dụng user_to_notify) ---
        timer_thread = SolverTimer(self.time_limit_seconds, self.user_to_notify)
        timer_thread.start()

        status = solver.Solve(model)

        timer_thread.stop()
        timer_thread.join()

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise ValueError("Không tìm thấy giải pháp trong thời gian cho phép.")

        # --- XUẤT KẾT QUẢ (LOG) ---
        # Code xuất kết quả giữ nguyên, nhưng sẽ chạy qua hàm self.log (đã force user=None)
        now = datetime.now()
        html_out = ""
        html_out += f"<b>Thời gian: {now.strftime('%d/%m/%Y %H:%M:%S')}</b><br>"
        self.log(html_out)
        
        # ... (Phần logic tính toán & tạo bảng giữ nguyên như cũ, chỉ cần gọi self.log là được) ...
        # (Để ngắn gọn mình không lặp lại đoạn tạo bảng HTML dài dòng ở đây vì logic đó bạn đã có, 
        # quan trọng nhất là các hàm log() đã được sửa thành user=None)

        return b_opt