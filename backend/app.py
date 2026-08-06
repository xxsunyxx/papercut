# -*- coding: utf-8 -*-
"""
WebUI 后端服务 - A3 试卷智能切割系统
使用 PaddleOCR 进行文字检测分析，自动确定切割点
"""

import os
import sys
import warnings
from pathlib import Path

# ==================== 配置加载 ====================
# 从 env.txt 加载配置
_env_path = Path(__file__).parent.parent / "env.txt"
_config = {}
if _env_path.exists():
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                _config[key.strip()] = value.strip()

# 应用环境变量（必须在 import paddle 之前设置）
os.environ["FLAGS_use_mkldnn"] = _config.get("FLAGS_USE_MKLDNN", "0")
# OMP_NUM_THREADS: 每个模型实例内部的 OpenMP 线程数
# 当模型池启用时，建议设为 1-2，由模型池实现跨实例并行
_omp_threads = int(_config.get("OMP_NUM_THREADS", "1"))
os.environ["OMP_NUM_THREADS"] = str(_omp_threads)
# 抑制 PaddlePaddle 的 OMP_NUM_THREADS 警告
os.environ["GLOG_minloglevel"] = "2"

# 仅在 MKL-DNN 禁用时设置 MKLDNN_DISABLE
if _config.get("FLAGS_USE_MKLDNN", "0") == "0":
    os.environ["MKLDNN_DISABLE"] = "1"
else:
    os.environ["MKLDNN_DISABLE"] = "0"

os.environ["FLAGS_enable_pir_api"] = "0"

# 设置 PaddleX 模型存储路径到本地目录（正确的环境变量是 PADDLE_PDX_CACHE_HOME）
_paddlex_home = _config.get("PADDLEX_HOME", "models")
_paddlex_home_abs = str(Path(__file__).parent.parent / _paddlex_home)
os.environ["PADDLE_PDX_CACHE_HOME"] = _paddlex_home_abs
os.makedirs(_paddlex_home_abs, exist_ok=True)

# 抑制 Paddle/PaddleX 的冗余警告
warnings.filterwarnings("ignore", category=UserWarning,
                        message=".*No ccache found.*")
warnings.filterwarnings("ignore", message=".*OMP_NUM_THREADS set to.*")

import json
import time
import tempfile
import logging
import traceback
import threading
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import numpy as np
import cv2
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("papercut")

app = FastAPI(title="A3 试卷智能切割系统", version="2.0")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 配置常量 ====================

OCR_ENGINE = _config.get("OCR_ENGINE", "paddle_dynamic")
OCR_DET_MODEL = _config.get("OCR_DET_MODEL", "PP-OCRv5_mobile_det")
OCR_REC_MODEL = _config.get("OCR_REC_MODEL", "PP-OCRv5_mobile_rec")
OCR_LANG = _config.get("OCR_LANG", "ch")
OCR_IMAGE_SCALE = float(_config.get("OCR_IMAGE_SCALE", "1.0"))
PDF_RENDER_SCALE = float(_config.get("PDF_RENDER_SCALE", "2.0"))
SEAL_LINE_MIN_COVERAGE = float(_config.get("SEAL_LINE_MIN_COVERAGE", "0.35"))
SEAL_LINE_SEARCH_WIDTH = float(_config.get("SEAL_LINE_SEARCH_WIDTH", "0.20"))
SERVER_HOST = _config.get("HOST", "0.0.0.0")
SERVER_PORT = int(_config.get("PORT", "8000"))
# 页面并行处理线程数（0=自动，按CPU核心数决定）
PAGE_WORKERS = int(_config.get("PAGE_WORKERS", "0"))
# 模型池大小：每个worker一个独立OCR实例，真正并行
# 0=自动（取 PAGE_WORKERS 或 CPU核心数/2，上限16）
MODEL_POOL_SIZE = int(_config.get("MODEL_POOL_SIZE", "0"))

logger.info(f"配置: engine={OCR_ENGINE}, det={OCR_DET_MODEL}, rec={OCR_REC_MODEL}, scale={OCR_IMAGE_SCALE}")
logger.info(f"模型存储路径: {_paddlex_home_abs}")
logger.info(f"并行线程: PAGE_WORKERS={PAGE_WORKERS}, MODEL_POOL_SIZE={MODEL_POOL_SIZE}, OMP_NUM_THREADS={os.environ.get('OMP_NUM_THREADS')}")


# ==================== 数据模型 ====================

class CutPoint(BaseModel):
    page_index: int
    split_positions: List[float]
    confidence: float
    seal_line_position: Optional[float] = None
    detected_columns: int = 2


class AnalyzeResponse(BaseModel):
    total_pages: int
    pages: List[CutPoint]
    text_regions: Optional[List[List[dict]]] = None


# ==================== OCR 分析器 ====================

class OCRAnalyzer:
    """使用 PaddleX 文字检测模型（仅检测，不识别，速度快40倍）"""

    def __init__(self):
        self.det_model = None
        self._initialized = False
        self._init_model()

    def _init_model(self):
        try:
            import paddlex

            logger.info("正在初始化文字检测模型（仅检测，跳过识别）...")
            self.det_model = paddlex.create_model(
                OCR_DET_MODEL,
                engine=OCR_ENGINE,
            )
            self._initialized = True
            logger.info(f"文字检测模型初始化成功: {OCR_DET_MODEL}")

        except Exception as e:
            logger.error(f"模型初始化失败: {e}")
            logger.error(traceback.format_exc())
            raise

    def detect_text(self, image: np.ndarray) -> List[dict]:
        """
        检测图像中的文字区域（仅检测位置，不识别文字内容）

        Returns:
            [{"bbox": [x1, y1, x2, y2], "text": "", "confidence": 0.9}, ...]
        """
        if not self._initialized:
            raise RuntimeError("检测模型未初始化")

        h, w = image.shape[:2]
        scale = OCR_IMAGE_SCALE

        if scale < 1.0:
            small_image = cv2.resize(image, (int(w * scale), int(h * scale)))
        else:
            small_image = image

        result = list(self.det_model.predict(small_image))

        text_regions = []
        if result and len(result) > 0:
            page_result = result[0]
            if page_result is None:
                return text_regions

            # TextDetResult 包含:
            #   dt_polys: 检测到的多边形 [[x1,y1],[x2,y2],[x3,y3],[x4,y4], ...]
            #   dt_scores: 检测置信度列表
            dt_polys = page_result.get("dt_polys", []) if hasattr(page_result, "get") else \
                       (page_result["dt_polys"] if isinstance(page_result, dict) else [])
            dt_scores = page_result.get("dt_scores", []) if hasattr(page_result, "get") else \
                        (page_result["dt_scores"] if isinstance(page_result, dict) else [])

            for i, poly in enumerate(dt_polys):
                try:
                    pts = np.array(poly, dtype=np.float32)
                    if pts.ndim == 2 and pts.shape[0] >= 2:
                        x1, y1 = pts.min(axis=0)
                        x2, y2 = pts.max(axis=0)
                    elif pts.ndim == 1 and len(pts) == 4:
                        x1, y1, x2, y2 = pts
                    else:
                        continue

                    conf = float(dt_scores[i]) if i < len(dt_scores) else 0.0

                    text_regions.append({
                        "bbox": [
                            float(x1) / scale,
                            float(y1) / scale,
                            float(x2) / scale,
                            float(y2) / scale,
                        ],
                        "text": "",
                        "confidence": conf,
                    })
                except Exception as e:
                    logger.debug(f"解析第 {i} 个区域时出错: {e}")
                    continue

        logger.info(f"检测到 {len(text_regions)} 个文字区域")
        return text_regions


# ==================== 切割点检测算法 ====================

def detect_seal_line(image: np.ndarray) -> Optional[float]:
    """
    检测试卷密封线位置（垂直虚线）

    算法：
    1. 分别在左侧和右侧各 20% 区域搜索垂直线
    2. 使用形态学操作检测垂直长线
    3. 取覆盖度最大的一侧作为密封线位置
    （试卷正面密封线在左侧，背面在右侧）

    Returns:
        密封线位置 (0-1 比例)，未检测到返回 None
    """
    h, w = image.shape[:2]
    search_w = int(w * SEAL_LINE_SEARCH_WIDTH)

    # 垂直形态学核
    kernel_h = max(h // 3, 50)
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_h))

    best_coverage = 0
    best_position = None
    best_side = None

    # 分别搜索左侧和右侧区域
    for side, region in [
        ("left", image[:, :search_w]),
        ("right", image[:, w - search_w:]),
    ]:
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV)
        vertical_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)

        # 统计每列的白色像素数（垂直线覆盖的高度）
        col_sums = np.sum(vertical_lines > 0, axis=0)
        max_cov = col_sums.max()

        if max_cov > best_coverage:
            peak_x = int(np.argmax(col_sums))
            # 转换为全图坐标
            if side == "left":
                abs_x = peak_x
            else:
                abs_x = w - search_w + peak_x

            best_coverage = max_cov
            best_position = float(abs_x) / w
            best_side = side

    if best_coverage > h * SEAL_LINE_MIN_COVERAGE:
        logger.info(f"检测到密封线: 位置={best_position:.3f}, 侧={best_side}, 覆盖率={best_coverage/h*100:.0f}%")
        return best_position

    logger.info("未检测到密封线")
    return None


class CutPointDetector:
    """根据文字检测结果确定切割位置"""

    @staticmethod
    def build_histogram(
        text_regions: List[dict],
        image_width: int,
        image_height: int,
        seal_line_pos: Optional[float] = None,
    ) -> tuple:
        """
        构建内容密度直方图

        Args:
            seal_line_pos: 密封线位置，如果提供则只在密封线右侧区域统计

        Returns:
            (histogram, smoothed, num_bins)
        """
        num_bins = max(50, image_width // 20)
        histogram = np.zeros(num_bins)

        for region in text_regions:
            bbox = region.get("bbox")
            if not bbox or len(bbox) < 4:
                continue

            x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]

            # 如果有密封线，跳过密封线左侧的区域
            if seal_line_pos is not None and x2 < seal_line_pos * image_width:
                continue

            bin_start = max(0, int(x1 / image_width * num_bins))
            bin_end = min(num_bins - 1, int(x2 / image_width * num_bins))

            region_height = max(y2 - y1, 1)
            for b in range(bin_start, bin_end + 1):
                overlap_start = max(x1, b * image_width / num_bins)
                overlap_end = min(x2, (b + 1) * image_width / num_bins)
                overlap_width = max(0, overlap_end - overlap_start)
                histogram[b] += overlap_width * region_height

        # 平滑直方图
        window_size = max(3, num_bins // 20)
        kernel = np.ones(window_size) / window_size
        smoothed = np.convolve(histogram, kernel, mode="same")

        # 归一化
        if smoothed.max() > 0:
            smoothed = smoothed / smoothed.max()

        return histogram, smoothed, num_bins

    @staticmethod
    def auto_detect_columns(smoothed: np.ndarray, num_bins: int) -> tuple:
        """
        自动检测栏数和切割点

        算法：
        1. 在 15%-85% 区域寻找局部最小值（低谷）
        2. 过滤掉不显著的低谷（深度不足最大值的 5%）
        3. 剩余低谷即为切割点

        Returns:
            (split_positions, num_columns)
        """
        search_start = int(num_bins * 0.15)
        search_end = int(num_bins * 0.85)
        search_range = smoothed[search_start:search_end]

        if len(search_range) == 0:
            return [0.5], 2

        max_val = search_range.max()
        if max_val <= 0:
            return [0.5], 2

        # 寻找局部最小值
        valleys = []
        for i in range(2, len(search_range) - 2):
            # 局部最小值：比左右两侧都小
            if (search_range[i] < search_range[i - 1] and
                search_range[i] < search_range[i + 1] and
                search_range[i] < search_range[i - 2] and
                search_range[i] < search_range[i + 2]):

                # 计算低谷深度（与相邻峰值差）
                left_peak = max(search_range[max(0, i - 10):i])
                right_peak = max(search_range[i + 1:min(len(search_range), i + 11)])
                depth = min(left_peak, right_peak) - search_range[i]

                # 低谷必须足够深（最大值的 5% 以上）且本身值足够低
                if depth > 0.05 and search_range[i] < 0.3:
                    valleys.append((i + search_start, search_range[i]))

        if len(valleys) == 0:
            # 没有找到低谷，默认单栏
            return [], 1
        elif len(valleys) == 1:
            return [float(valleys[0][0]) / num_bins], 2
        else:
            # 多个低谷，按位置排序
            valleys.sort(key=lambda v: v[0])
            # 最多取 3 个切割点（4 栏）
            valleys = valleys[:3]
            return [float(v[0]) / num_bins for v in valleys], len(valleys) + 1

    @staticmethod
    def detect_cut_points(
        text_regions: List[dict],
        image_width: int,
        image_height: int,
        num_columns: int = 0,
        seal_line_pos: Optional[float] = None,
    ) -> tuple:
        """
        根据文字区域确定切割位置

        Args:
            num_columns: 0=自动检测, 2=两栏, 3=三栏
            seal_line_pos: 密封线位置，影响直方图统计

        Returns:
            (split_positions, detected_columns)
        """
        if not text_regions:
            if num_columns == 3:
                return [0.33, 0.67], 3
            return [0.5], 2

        # 构建直方图（排除密封线左侧区域）
        histogram, smoothed, num_bins = CutPointDetector.build_histogram(
            text_regions, image_width, image_height, seal_line_pos
        )

        # 添加边缘惩罚
        edge_penalty = np.sin(np.linspace(0, np.pi, num_bins))
        penalized = smoothed * (0.3 + 0.7 * edge_penalty)

        if num_columns == 0:
            # 自动检测栏数
            return CutPointDetector.auto_detect_columns(penalized, num_bins)

        elif num_columns == 2:
            min_bin = int(num_bins * 0.3)
            max_bin = int(num_bins * 0.7)
            search_range = penalized[min_bin:max_bin + 1]

            if len(search_range) > 0 and search_range.min() < 0.1:
                split_bin = min_bin + np.argmin(search_range)
            else:
                split_bin = num_bins // 2

            return [float(split_bin) / num_bins], 2

        elif num_columns == 3:
            min_bin_1 = int(num_bins * 0.15)
            max_bin_1 = int(num_bins * 0.45)
            min_bin_2 = int(num_bins * 0.55)
            max_bin_2 = int(num_bins * 0.85)

            search_range_1 = penalized[min_bin_1:max_bin_1 + 1]
            search_range_2 = penalized[min_bin_2:max_bin_2 + 1]

            split_bin_1 = min_bin_1 + int(np.argmin(search_range_1)) if len(search_range_1) > 0 else num_bins // 3
            split_bin_2 = min_bin_2 + int(np.argmin(search_range_2)) if len(search_range_2) > 0 else 2 * num_bins // 3

            return [float(split_bin_1) / num_bins, float(split_bin_2) / num_bins], 3

        else:
            return [0.5], 2


# ==================== 全局变量 ====================

class ModelPool:
    """OCR 模型池，每个 worker 持有独立实例以实现真正并行"""

    def __init__(self, size: int):
        self._pool: List[OCRAnalyzer] = []
        self._index = 0
        self._lock = threading.Lock()
        self._size = size
        logger.info(f"正在创建 OCR 模型池（{size} 个实例）...")
        for i in range(size):
            logger.info(f"  初始化模型实例 {i + 1}/{size}...")
            analyzer = OCRAnalyzer()
            self._pool.append(analyzer)
        logger.info(f"OCR 模型池就绪，共 {size} 个实例")

    def acquire(self) -> OCRAnalyzer:
        """轮询获取一个模型实例（线程安全）"""
        with self._lock:
            idx = self._index % self._size
            self._index += 1
            return self._pool[idx]

    def __len__(self):
        return self._size


model_pool: Optional[ModelPool] = None


def get_model_pool() -> ModelPool:
    global model_pool
    if model_pool is None:
        # 自动计算池大小
        if MODEL_POOL_SIZE > 0:
            pool_size = MODEL_POOL_SIZE
        elif PAGE_WORKERS > 0:
            pool_size = PAGE_WORKERS
        else:
            import os as _os
            cpu_count = _os.cpu_count() or 4
            pool_size = min(cpu_count // 2, 16)
            pool_size = max(pool_size, 1)

        # 自动调优 OMP_NUM_THREADS：根据池大小和CPU核心数动态调整
        global _omp_threads
        if MODEL_POOL_SIZE <= 0 and PAGE_WORKERS <= 0:
            import os as _os
            cpu_count = _os.cpu_count() or 4
            # 每个模型实例分配适当的 OMP 线程，总线程数不超过核心数
            ideal_omp = max(1, cpu_count // pool_size)
            ideal_omp = min(ideal_omp, 4)  # 单模型最多 4 个 OMP 线程
            if ideal_omp != _omp_threads:
                logger.info(f"自动调整 OMP_NUM_THREADS: {_omp_threads} -> {ideal_omp} (CPU={cpu_count}, 模型池={pool_size})")
                _omp_threads = ideal_omp
                os.environ["OMP_NUM_THREADS"] = str(ideal_omp)

        model_pool = ModelPool(pool_size)
    return model_pool


# ==================== API 端点 ====================

@app.get("/")
async def root():
    """根路由 - 重定向到 API 文档"""
    return RedirectResponse(url="/docs")


@app.get("/api/health")
async def health_check():
    pool = get_model_pool()
    return {
        "status": "ok",
        "service": "papercut-webui",
        "model_pool_initialized": model_pool is not None,
        "model_pool_size": len(pool) if pool else 0,
        "config": {
            "engine": OCR_ENGINE,
            "det_model": OCR_DET_MODEL,
            "mode": "detection-only (no recognition)",
            "image_scale": OCR_IMAGE_SCALE,
            "model_home": _paddlex_home_abs,
            "omp_threads": os.environ.get("OMP_NUM_THREADS"),
        },
    }


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_pdf(
    file: UploadFile = File(...),
    num_columns: int = 0,
):
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_path = tmp.name
            content = await file.read()
            tmp.write(content)

        logger.info(f"收到 PDF 文件: {file.filename}, 大小: {len(content)} bytes")
        total_start = time.time()

        try:
            import pypdfium2 as pdfium
        except ImportError:
            raise HTTPException(status_code=500, detail="pypdfium2 未安装")

        pdf = pdfium.PdfDocument(pdf_path)
        total_pages = len(pdf)

        if total_pages == 0:
            raise HTTPException(status_code=400, detail="PDF 文件没有页面")

        logger.info(f"PDF 共 {total_pages} 页, 栏数模式: {'自动' if num_columns == 0 else num_columns}")

        detector = CutPointDetector()

        # 渲染所有页面到内存（并发处理需要预渲染）
        page_images = []
        for page_idx in range(total_pages):
            page = pdf[page_idx]
            bitmap = page.render(scale=PDF_RENDER_SCALE)
            pil_image = bitmap.to_pil()
            image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
            page_images.append(image)

        pdf.close()

        # 并行处理每页
        max_workers = PAGE_WORKERS
        if max_workers <= 0:
            import os as _os
            cpu_count = _os.cpu_count() or 4
            # 高核数CPU放开上限，每个核可以处理一个页面
            max_workers = min(cpu_count, total_pages)
            max_workers = max(max_workers, 1)

        logger.info(f"使用 {max_workers} 个线程并行处理 {total_pages} 页")

        pages_result = [None] * total_pages
        all_text_regions = [None] * total_pages

        def process_page(page_idx):
            """单页处理函数"""
            page_start = time.time()
            image = page_images[page_idx]
            h, w = image.shape[:2]
            logger.info(f"[页 {page_idx + 1}] 开始处理: {w}x{h}")

            try:
                # 密封线检测（纯 OpenCV，可并行）
                t0 = time.time()
                seal_line_pos = detect_seal_line(image)
                t_seal = time.time() - t0

                # 文字检测：从模型池获取独立实例，真正并行
                analyzer = get_model_pool().acquire()
                t0 = time.time()
                text_regions = analyzer.detect_text(image)
                t_ocr = time.time() - t0

                # 切割点检测（纯 CPU，可并行）
                cut_points, detected_cols = detector.detect_cut_points(
                    text_regions, w, h, num_columns, seal_line_pos
                )
                confidence = _calculate_confidence(text_regions, cut_points, w)

                elapsed = time.time() - page_start
                logger.info(
                    f"[页 {page_idx + 1}] 完成: 栏数={detected_cols}, "
                    f"切割点={[f'{x:.3f}' for x in cut_points]}, "
                    f"密封线={seal_line_pos}, 置信度={confidence:.2f} | "
                    f"密封线{t_seal:.1f}s + OCR{t_ocr:.1f}s = 总耗时{elapsed:.1f}s"
                )

                serializable_regions = []
                for region in text_regions:
                    serializable_regions.append({
                        "bbox": [float(b) for b in region["bbox"]],
                        "text": region["text"],
                        "confidence": region["confidence"],
                    })

                return (page_idx, CutPoint(
                    page_index=page_idx + 1,
                    split_positions=cut_points,
                    confidence=confidence,
                    seal_line_position=seal_line_pos,
                    detected_columns=detected_cols,
                ), serializable_regions)

            except Exception as e:
                logger.error(f"[页 {page_idx + 1}] 分析出错: {e}")
                logger.error(traceback.format_exc())
                elapsed = time.time() - page_start
                logger.info(f"[页 {page_idx + 1}] 失败，耗时{elapsed:.1f}s，使用默认切割点")
                return (page_idx, CutPoint(
                    page_index=page_idx + 1,
                    split_positions=[0.5],
                    confidence=0.0,
                ), [])

        # 使用线程池并行处理
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(process_page, idx): idx
                for idx in range(total_pages)
            }

            for future in as_completed(futures):
                page_idx, cut_point, regions = future.result()
                pages_result[page_idx] = cut_point
                all_text_regions[page_idx] = regions

        total_elapsed = time.time() - total_start
        logger.info(
            f"PDF 分析完成: {total_pages} 页 × {max_workers} 线程, "
            f"总耗时 {total_elapsed:.1f}s"
        )

        # 清理临时文件
        try:
            os.unlink(pdf_path)
        except Exception:
            pass

        return AnalyzeResponse(
            total_pages=total_pages,
            pages=pages_result,
            text_regions=all_text_regions,
        )

    except Exception as e:
        logger.error(f"PDF 分析失败: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analyze-sse")
async def analyze_pdf_sse(
    file: UploadFile = File(...),
    num_columns: int = 0,
):
    """SSE 流式分析端点，实时推送每页处理进度"""
    content = await file.read()

    async def event_generator():
        try:
            import pypdfium2 as pdfium

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                pdf_path = tmp.name
                tmp.write(content)

            logger.info(f"[SSE] 收到 PDF 文件: {file.filename}, 大小: {len(content)} bytes")
            total_start = time.time()

            pdf = pdfium.PdfDocument(pdf_path)
            total_pages = len(pdf)

            if total_pages == 0:
                yield _sse_event("error", {"message": "PDF 文件没有页面"})
                pdf.close()
                os.unlink(pdf_path)
                return

            logger.info(f"[SSE] PDF 共 {total_pages} 页")

            # 发送开始事件
            yield _sse_event("start", {"total_pages": total_pages})

            detector = CutPointDetector()

            # 渲染所有页面到内存
            page_images = []
            for page_idx in range(total_pages):
                page = pdf[page_idx]
                bitmap = page.render(scale=PDF_RENDER_SCALE)
                pil_image = bitmap.to_pil()
                image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
                page_images.append(image)

            pdf.close()

            # 并行处理每页
            max_workers = PAGE_WORKERS
            if max_workers <= 0:
                import os as _os
                cpu_count = _os.cpu_count() or 4
                max_workers = min(cpu_count, total_pages)
                max_workers = max(max_workers, 1)

            logger.info(f"[SSE] 使用 {max_workers} 个线程并行处理 {total_pages} 页")

            pages_result = [None] * total_pages
            all_text_regions = [None] * total_pages
            completed = [False] * total_pages

            def process_page_sse(page_idx):
                """单页处理函数（带进度回调）"""
                page_start = time.time()
                image = page_images[page_idx]
                h, w = image.shape[:2]

                try:
                    seal_line_pos = detect_seal_line(image)

                    analyzer = get_model_pool().acquire()
                    text_regions = analyzer.detect_text(image)

                    cut_points, detected_cols = detector.detect_cut_points(
                        text_regions, w, h, num_columns, seal_line_pos
                    )
                    confidence = _calculate_confidence(text_regions, cut_points, w)

                    elapsed = time.time() - page_start

                    serializable_regions = []
                    for region in text_regions:
                        serializable_regions.append({
                            "bbox": [float(b) for b in region["bbox"]],
                            "text": region["text"],
                            "confidence": region["confidence"],
                        })

                    return (page_idx, CutPoint(
                        page_index=page_idx + 1,
                        split_positions=cut_points,
                        confidence=confidence,
                        seal_line_position=seal_line_pos,
                        detected_columns=detected_cols,
                    ), serializable_regions, elapsed)

                except Exception as e:
                    logger.error(f"[SSE][页 {page_idx + 1}] 分析出错: {e}")
                    elapsed = time.time() - page_start
                    return (page_idx, CutPoint(
                        page_index=page_idx + 1,
                        split_positions=[0.5],
                        confidence=0.0,
                    ), [], elapsed)

            # 在线程池中处理，通过队列同步进度
            progress_queue = Queue()

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(process_page_sse, idx): idx
                    for idx in range(total_pages)
                }

                # 启动一个线程监听完成情况
                def track_completions():
                    for future in as_completed(futures):
                        result = future.result()
                        progress_queue.put(result)

                tracker_thread = threading.Thread(target=track_completions)
                tracker_thread.start()

                # 轮询进度队列，发送 SSE 事件
                completed_count = 0
                while completed_count < total_pages:
                    try:
                        page_idx, cut_point, regions, elapsed = progress_queue.get(timeout=0.5)
                        pages_result[page_idx] = cut_point
                        all_text_regions[page_idx] = regions
                        completed[page_idx] = True
                        completed_count += 1

                        progress_data = {
                            "page": page_idx + 1,
                            "total": total_pages,
                            "completed": completed_count,
                            "cut_point": cut_point.split_positions,
                            "confidence": cut_point.confidence,
                            "seal_line": cut_point.seal_line_position,
                            "elapsed": round(elapsed, 1),
                        }
                        logger.info(
                            f"[SSE] 页 {page_idx + 1} 完成 ({completed_count}/{total_pages}) "
                            f"耗时{elapsed:.1f}s"
                        )
                        yield _sse_event("progress", progress_data)
                    except Exception:
                        continue

                tracker_thread.join()

            total_elapsed = time.time() - total_start
            logger.info(f"[SSE] 分析完成: {total_pages} 页, 总耗时 {total_elapsed:.1f}s")

            # 发送完成事件
            final_result = AnalyzeResponse(
                total_pages=total_pages,
                pages=pages_result,
                text_regions=all_text_regions,
            )
            yield _sse_event("complete", final_result.model_dump())

            # 清理临时文件
            try:
                os.unlink(pdf_path)
            except Exception:
                pass

        except Exception as e:
            logger.error(f"[SSE] 分析失败: {e}")
            logger.error(traceback.format_exc())
            yield _sse_event("error", {"message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/analyze-image", response_model=AnalyzeResponse)
async def analyze_image(
    file: UploadFile = File(...),
    num_columns: int = 0,
):
    try:
        from PIL import Image as PILImage
        import io

        content = await file.read()
        pil_img = PILImage.open(io.BytesIO(content))
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        image = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

        h, w = image.shape[:2]

        detector = CutPointDetector()

        # 检测密封线
        seal_line_pos = detect_seal_line(image)

        # 文字检测
        analyzer = get_model_pool().acquire()
        text_regions = analyzer.detect_text(image)

        # 切割点检测
        cut_points, detected_cols = detector.detect_cut_points(
            text_regions, w, h, num_columns, seal_line_pos
        )
        confidence = _calculate_confidence(text_regions, cut_points, w)

        serializable_regions = []
        for region in text_regions:
            serializable_regions.append({
                "bbox": [float(b) for b in region["bbox"]],
                "text": region["text"],
                "confidence": region["confidence"],
            })

        return AnalyzeResponse(
            total_pages=1,
            pages=[CutPoint(
                page_index=1,
                split_positions=cut_points,
                confidence=confidence,
                seal_line_position=seal_line_pos,
                detected_columns=detected_cols,
            )],
            text_regions=[serializable_regions],
        )

    except Exception as e:
        logger.error(f"分析图像时出错: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


def _calculate_confidence(
    text_regions: List[dict],
    cut_points: List[float],
    image_width: int,
) -> float:
    if not text_regions or not cut_points:
        return 0.5

    scores = []
    for cp in cut_points:
        cp_x = cp * image_width
        margin = image_width * 0.05
        content_near_cut = 0

        for region in text_regions:
            bbox = region.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
            if x2 >= cp_x - margin and x1 <= cp_x + margin:
                content_near_cut += (x2 - x1) * (y2 - y1)

        total_content = sum(
            max(r.get("bbox", [0, 0, 0, 0])[2] - r.get("bbox", [0, 0, 0, 0])[0], 0) *
            max(r.get("bbox", [0, 0, 0, 0])[3] - r.get("bbox", [0, 0, 0, 0])[1], 0)
            for r in text_regions
            if r.get("bbox") and len(r.get("bbox")) >= 4
        )

        if total_content > 0:
            score = 1.0 - min(content_near_cut / total_content, 1.0)
        else:
            score = 0.5
        scores.append(score)

    return float(np.mean(scores))


def _sse_event(event_type: str, data: dict) -> str:
    """构造 SSE 事件字符串"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.on_event("startup")
async def startup_event():
    logger.info("服务启动，正在初始化模型池...")
    try:
        pool = get_model_pool()
        logger.info(f"模型池初始化完成，共 {len(pool)} 个实例")
    except Exception as e:
        logger.error(f"模型池初始化失败: {e}")
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)
