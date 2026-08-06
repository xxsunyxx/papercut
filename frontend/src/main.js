import { elements } from './dom.js';
import { state } from './state.js';
import { handleFileUpload } from './file-handler.js';
import { changePage, renderCurrentPage } from './viewer.js';
import {
    toggleSealLine,
    applySplitToType,
    applySplitToAll,
    resetToHalf,
    setThreeColumn,
    addSplitLine,
    removeSplitLine,
    setSplitPositionsForPage,
} from './editor.js';
import { exportPdf, getQualityConfig } from './exporter.js';
import { analyzePdfSse, analyzeImage, checkApiHealth } from './api.js';

/**
 * 初始化所有事件监听器
 */
function initEventListeners() {
    // 文件上传
    elements.uploadBtn.addEventListener('click', () => elements.fileInput.click());
    if (elements.changeFileBtn) {
        elements.changeFileBtn.addEventListener('click', () => elements.fileInput.click());
    }
    elements.fileInput.addEventListener('change', handleFileUpload);

    // 页面导航
    elements.prevPageBtn.addEventListener('click', () => changePage(state.currentPage - 1));
    elements.nextPageBtn.addEventListener('click', () => changePage(state.currentPage + 1));

    // 编辑工具
    elements.toggleSealLineBtn.addEventListener('click', toggleSealLine);
    elements.applyToTypeBtn.addEventListener('click', () => applySplitToType());
    elements.applyToAllBtn.addEventListener('click', () => applySplitToAll());
    elements.exportBtn.addEventListener('click', exportPdf);

    // 质量滑块
    if (elements.qualitySlider) {
        const updateSliderVisual = () => {
            const level = parseInt(elements.qualitySlider.value);
            const cfg = getQualityConfig(level);
            if (elements.qualityLabel) {
                elements.qualityLabel.textContent = cfg.name;
            }
            const pct = (level / 3) * 100;
            elements.qualitySlider.style.background =
                `linear-gradient(to right, var(--primary) 0%, var(--primary) ${pct}%, var(--border) ${pct}%, var(--border) 100%)`;
        };

        elements.qualitySlider.addEventListener('input', updateSliderVisual);
        updateSliderVisual();
    }

    // 新增按钮
    if (elements.resetSplitLinesBtn) {
        elements.resetSplitLinesBtn.addEventListener('click', resetToHalf);
    }
    if (elements.threeColumnBtn) {
        elements.threeColumnBtn.addEventListener('click', setThreeColumn);
    }
    if (elements.addSplitLineBtn) {
        elements.addSplitLineBtn.addEventListener('click', addSplitLine);
    }
    if (elements.removeSplitLineBtn) {
        elements.removeSplitLineBtn.addEventListener('click', removeSplitLine);
    }

    // AI 自动检测按钮
    if (elements.autoDetectBtn) {
        elements.autoDetectBtn.addEventListener('click', handleAutoDetect);
    }

    // 窗口大小调整
    window.addEventListener('resize', handleResize);

    // 拖拽事件
    const dropZone = elements.canvasContainer;
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });
    dropZone.addEventListener('dragenter', highlight, false);
    dropZone.addEventListener('dragover', highlight, false);
    dropZone.addEventListener('dragleave', unhighlight, false);
    dropZone.addEventListener('drop', handleDrop, false);

    // 启动时检查 API 状态
    checkApiHealth().then(connected => {
        state.apiConnected = connected;
        updateApiStatusDisplay();
    });

    // 定期检查 API 状态 (每30秒)
    setInterval(async () => {
        const connected = await checkApiHealth();
        if (connected !== state.apiConnected) {
            state.apiConnected = connected;
            updateApiStatusDisplay();
        }
    }, 30000);
}

/**
 * 更新 API 状态显示
 */
function updateApiStatusDisplay() {
    if (!elements.apiStatus) return;
    if (state.apiConnected) {
        elements.apiStatus.className = 'api-status status-connected';
        elements.apiStatus.querySelector('.status-text').textContent = 'AI 后端已连接';
    } else {
        elements.apiStatus.className = 'api-status status-disconnected';
        elements.apiStatus.querySelector('.status-text').textContent = 'AI 后端未连接';
    }
}

/**
 * 处理 AI 自动检测请求
 */
async function handleAutoDetect() {
    if (!state._currentFile) {
        alert('请先上传文件');
        return;
    }

    if (!state.apiConnected) {
        alert('AI 后端未连接，请先启动后端服务');
        return;
    }

    const numColumns = 0;
    const originalText = elements.autoDetectBtn.innerHTML;
    elements.autoDetectBtn.disabled = true;
    elements.autoDetectBtn.innerHTML = '<span class="material-icons">hourglass_empty</span> 分析中...';

    // 显示进度遮罩
    if (elements.analyzingOverlay) {
        elements.analyzingOverlay.classList.remove('hidden');
        elements.analyzingText.textContent = '正在连接后端...';
        elements.progressFill.style.width = '0%';
        elements.progressText.textContent = '0 / 0';
    }

    try {
        if (state.isPdf) {
            // PDF 使用 SSE 流式进度
            const result = await analyzePdfSse(state._currentFile, numColumns, {
                onStart: (totalPages) => {
                    if (elements.analyzingText) {
                        elements.analyzingText.textContent = `开始分析，共 ${totalPages} 页...`;
                    }
                    if (elements.progressText) {
                        elements.progressText.textContent = `0 / ${totalPages}`;
                    }
                },
                onProgress: (data) => {
                    const pct = (data.completed / data.total) * 100;
                    if (elements.progressFill) {
                        elements.progressFill.style.width = `${pct}%`;
                    }
                    if (elements.progressText) {
                        elements.progressText.textContent = `${data.completed} / ${data.total}`;
                    }
                    if (elements.analyzingText) {
                        const cutStr = data.cut_point && data.cut_point.length > 0
                            ? ` [${data.cut_point.map(p => (p * 100).toFixed(0) + '%').join(',')}]`
                            : '';
                        const sealStr = data.seal_line != null && data.seal_line !== undefined
                            ? ` 密封线:${(data.seal_line * 100).toFixed(0)}%`
                            : '';
                        elements.analyzingText.textContent =
                            `第 ${data.page} 页完成${cutStr}${sealStr} (耗时 ${data.elapsed}s)`;
                    }
                },
            });

            // 应用分析结果
            if (result.pages && result.pages.length > 0) {
                for (const pageResult of result.pages) {
                    setSplitPositionsForPage(
                        pageResult.page_index,
                        pageResult.split_positions,
                        pageResult.seal_line_position
                    );
                }

                renderCurrentPage();

                // 显示完成提示
                setTimeout(() => {
                    if (elements.analyzingOverlay) {
                        elements.analyzingOverlay.classList.add('hidden');
                    }

                    const summary = result.pages.map(p => {
                        const posStr = p.split_positions.map(pos => (pos * 100).toFixed(0) + '%').join(', ');
                        const sealStr = p.seal_line_position != null && p.seal_line_position !== undefined
                            ? ` 密封线:${(p.seal_line_position * 100).toFixed(0)}%` : '';
                        const colStr = p.detected_columns ? ` ${p.detected_columns}栏` : '';
                        return `第${p.page_index}页: ${colStr} [${posStr}]${sealStr} 置信度:${(p.confidence * 100).toFixed(0)}%`;
                    }).join('\n');

                    console.log('AI 分析结果:\n' + summary);
                    alert(`版面分析完成！\n\n检测结果:\n${summary}\n\n已自动应用切割点和密封线，您可以继续微调或直接导出。`);
                }, 200);
            } else {
                throw new Error('分析结果为空');
            }
        } else {
            // 图片仍使用原方式
            const result = await analyzeImage(state._currentFile, numColumns);

            if (result.pages && result.pages.length > 0) {
                for (const pageResult of result.pages) {
                    setSplitPositionsForPage(
                        pageResult.page_index,
                        pageResult.split_positions,
                        pageResult.seal_line_position
                    );
                }
                renderCurrentPage();

                setTimeout(() => {
                    if (elements.analyzingOverlay) {
                        elements.analyzingOverlay.classList.add('hidden');
                    }
                    alert('图片分析完成！');
                }, 300);
            }
        }
    } catch (error) {
        console.error('AI 分析失败:', error);
        if (elements.analyzingOverlay) {
            elements.analyzingOverlay.classList.add('hidden');
        }
        alert('AI 分析失败: ' + error.message);
    } finally {
        elements.autoDetectBtn.disabled = false;
        elements.autoDetectBtn.innerHTML = originalText;
    }
}

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

function highlight(e) {
    elements.dragOverlay.classList.remove('hidden');
}

function unhighlight(e) {
    if (e.target === elements.dragOverlay) {
        elements.dragOverlay.classList.add('hidden');
    }
}

function handleDrop(e) {
    unhighlight(e);
    elements.dragOverlay.classList.add('hidden');
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files.length > 0) {
        handleFileUpload({ target: { files: files } });
    }
}

let resizeTimer = null;
function handleResize() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
        if (state.pdfDoc || state.fileData) {
            renderCurrentPage();
        }
    }, 150);
}

// 启动程序
initEventListeners();