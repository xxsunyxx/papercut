import { state } from './state.js';
import { elements } from './dom.js';
import { renderSplitLines } from './editor.js';

/**
 * 切换到指定页面
 */
export function changePage(pageNum) {
    if (pageNum < 1 || pageNum > state.totalPages) return;

    state.currentPage = pageNum;
    updatePageControls();

    // 更新缩略图选中状态
    const thumbs = elements.thumbnailsPanel.querySelectorAll('.thumbnail-item');
    thumbs.forEach(t => t.classList.remove('active'));
    if (thumbs[pageNum - 1]) thumbs[pageNum - 1].classList.add('active');

    renderCurrentPage();
}

/**
 * 更新分页控件状态
 */
export function updatePageControls() {
    elements.pageInfo.textContent = `${state.currentPage} / ${state.totalPages}`;
    elements.prevPageBtn.disabled = state.currentPage <= 1;
    elements.nextPageBtn.disabled = state.currentPage >= state.totalPages;
}

/**
 * 渲染当前主页面的 Canvas
 */
let renderToken = 0;

export async function renderCurrentPage() {
    const myToken = ++renderToken;

    let canvas, viewport;

    if (state.isPdf) {
        const page = await state.pdfDoc.getPage(state.currentPage);
        const unscaledViewport = page.getViewport({ scale: 1 });

        const availableWidth = elements.canvasContainer.clientWidth - 40;
        const availableHeight = elements.canvasContainer.clientHeight - 40;

        const scaleX = availableWidth / unscaledViewport.width;
        const scaleY = availableHeight / unscaledViewport.height;
        let scale = Math.min(scaleX, scaleY);
        if (scale > 1.5) scale = 1.5;

        viewport = page.getViewport({ scale: scale });
        canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        canvas.height = viewport.height;
        canvas.width = viewport.width;

        await page.render({
            canvasContext: context,
            viewport: viewport
        }).promise;
    } else {
        const img = new Image();
        await new Promise((resolve, reject) => {
            img.onload = resolve;
            img.onerror = reject;
            img.src = state.fileData;
        });

        const availableWidth = elements.canvasContainer.clientWidth - 40;
        const availableHeight = elements.canvasContainer.clientHeight - 40;

        const scaleX = availableWidth / img.width;
        const scaleY = availableHeight / img.height;
        let scale = Math.min(scaleX, scaleY);
        if (scale > 1) scale = 1;

        canvas = document.createElement('canvas');
        canvas.width = img.width * scale;
        canvas.height = img.height * scale;
        const context = canvas.getContext('2d');
        context.drawImage(img, 0, 0, canvas.width, canvas.height);

        viewport = { width: canvas.width, height: canvas.height };
    }

    if (myToken !== renderToken) return;

    elements.canvasWrapper.innerHTML = '';
    elements.canvasWrapper.style.width = `${canvas.width}px`;
    elements.canvasWrapper.style.height = `${canvas.height}px`;
    elements.canvasWrapper.appendChild(canvas);

    renderSplitLines();
}

/**
 * 渲染左侧缩略图列表
 */
export async function renderThumbnails() {
    elements.thumbnailsPanel.innerHTML = '';

    for (let i = 1; i <= state.totalPages; i++) {
        const thumbainer = document.createElement('div');
        thumbainer.className = `thumbnail-item ${i === state.currentPage ? 'active' : ''}`;
        thumbainer.dataset.pageNumber = i;
        thumbainer.onclick = () => changePage(i);

        let canvas;

        if (state.isPdf) {
            const page = await state.pdfDoc.getPage(i);
            const viewport = page.getViewport({ scale: 0.2 });
            canvas = document.createElement('canvas');
            const context = canvas.getContext('2d');
            canvas.height = viewport.height;
            canvas.width = viewport.width;

            await page.render({
                canvasContext: context,
                viewport: viewport
            }).promise;
        } else {
            const img = new Image();
            img.src = state.fileData;
            await new Promise(r => img.onload = r);

            const scale = 0.2;
            canvas = document.createElement('canvas');
            canvas.width = img.width * scale;
            canvas.height = img.height * scale;
            canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        }

        const pageNum = document.createElement('div');
        pageNum.className = 'page-number';
        pageNum.textContent = i;

        thumbainer.appendChild(canvas);
        thumbainer.appendChild(pageNum);
        elements.thumbnailsPanel.appendChild(thumbainer);
    }
}