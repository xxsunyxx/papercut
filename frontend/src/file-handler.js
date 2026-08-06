import * as pdfjsLib from 'pdfjs-dist';
import { version } from 'pdfjs-dist/package.json';
import { state, resetState } from './state.js';
import { elements } from './dom.js';
import { renderThumbnails, renderCurrentPage, updatePageControls } from './viewer.js';
import { checkApiHealth } from './api.js';

// 设置 PDF.js Worker
pdfjsLib.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${version}/build/pdf.worker.min.mjs`;

/**
 * 处理文件上传事件
 */
export async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    resetState();
    state.fileName = file.name.replace(/\.[^/.]+$/, "");

    if (file.type === 'application/pdf') {
        state.isPdf = true;
    } else if (file.type.startsWith('image/')) {
        state.isPdf = false;
    } else {
        alert('不支持的文件格式，请上传 PDF 或图片文件');
        return;
    }

    elements.thumbnailsPanel.innerHTML = '';
    elements.emptyState.style.display = 'none';

    // 显示缩略图面板（纵向排列）
    const leftPanel = document.querySelector('.left-panel');
    if (leftPanel) {
        leftPanel.style.display = 'block';
    }

    // 启用相关按钮
    elements.toggleSealLineBtn.disabled = false;
    elements.exportBtn.disabled = false;
    elements.applyToTypeBtn.disabled = false;
    elements.applyToAllBtn.disabled = false;

    if (state.isPdf) {
        const arrayBuffer = await file.arrayBuffer();
        await loadPdf(arrayBuffer);
    } else {
        loadImage(file);
    }

    // 保存文件引用用于 AI 分析
    state._currentFile = file;

    // 检查 API 状态
    const apiOk = await checkApiHealth();
    state.apiConnected = apiOk;
    updateApiStatus();
}

/**
 * 更新 API 状态显示
 */
function updateApiStatus() {
    if (state.apiConnected) {
        elements.apiStatus.className = 'api-status status-connected';
        elements.apiStatus.querySelector('.status-text').textContent = 'AI 后端已连接';
    } else {
        elements.apiStatus.className = 'api-status status-disconnected';
        elements.apiStatus.querySelector('.status-text').textContent = 'AI 后端未连接';
    }
}

/**
 * 加载并解析 PDF 文件
 */
async function loadPdf(arrayBuffer) {
    try {
        const loadingTask = pdfjsLib.getDocument({ data: arrayBuffer });
        state.pdfDoc = await loadingTask.promise;
        state.totalPages = state.pdfDoc.numPages;
        state.currentPage = 1;

        updatePageControls();
        await renderThumbnails();
        renderCurrentPage();
    } catch (error) {
        console.error('Error loading PDF:', error);
        alert('无法加载 PDF 文件');
    }
}

/**
 * 加载图片文件
 */
function loadImage(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        state.fileData = e.target.result;
        state.totalPages = 1;
        state.currentPage = 1;
        state.pdfDoc = null;

        updatePageControls();
        elements.thumbnailsPanel.innerHTML = '';
        const thumb = document.createElement('div');
        thumb.className = 'thumbnail-item active';
        const img = document.createElement('img');
        img.src = state.fileData;
        img.style.width = '100%';
        thumb.appendChild(img);
        elements.thumbnailsPanel.appendChild(thumb);

        renderCurrentPage();
    };
    reader.readAsDataURL(file);
}