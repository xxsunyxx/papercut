import { state } from './state.js';
import { elements } from './dom.js';

/**
 * 获取或初始化当前页面的配置
 * 结构: {
 *   splitLines: [{ x: 0.5, type: 'split' }],  // 分割线列表
 *   sealLine: null | { x: 0.15, type: 'left'|'right' }
 * }
 */
export function getPageConfig(pageIndex) {
    if (!state.pagesData[pageIndex]) {
        state.pagesData[pageIndex] = {
            splitLines: [{ x: 0.5, type: 'split' }],
            sealLine: null,
        };
    }
    return state.pagesData[pageIndex];
}

/**
 * 渲染当前页的所有辅助线
 */
export function renderSplitLines() {
    // 清除现有的线
    elements.canvasWrapper.querySelectorAll('.split-line').forEach(e => e.remove());

    const config = getPageConfig(state.currentPage);

    // 渲染所有分割线
    config.splitLines.forEach((line, index) => {
        createLineElement(line.x, 'split', (newX) => {
            config.splitLines[index].x = newX;
        }, index + 1, () => {
            // 删除此分割线（至少保留1条）
            if (config.splitLines.length > 1) {
                config.splitLines.splice(index, 1);
                renderSplitLines();
            }
        });
    });

    // 渲染密封线
    if (config.sealLine) {
        createLineElement(config.sealLine.x, 'seal', (newX) => {
            config.sealLine.x = newX;
        }, null, () => {
            // 删除密封线
            config.sealLine = null;
            renderSplitLines();
        });

        elements.toggleSealLineBtn.innerHTML = '<span class="material-icons">close</span> 取消去除';
        elements.toggleSealLineBtn.classList.add('active-state');
    } else {
        elements.toggleSealLineBtn.innerHTML = '<span class="material-icons">format_shapes</span> 去除密封线';
        elements.toggleSealLineBtn.classList.remove('active-state');
    }

    // 启用相关操作按钮
    elements.toggleSealLineBtn.disabled = false;
    elements.applyToTypeBtn.disabled = false;
    elements.applyToAllBtn.disabled = false;
    elements.autoDetectBtn.disabled = false;
    elements.resetSplitLinesBtn.disabled = false;
    elements.threeColumnBtn.disabled = false;
    elements.addSplitLineBtn.disabled = false;
    elements.removeSplitLineBtn.disabled = config.splitLines.length <= 1;
}

/**
 * 创建辅助线 DOM 元素并绑定拖拽事件
 */
function createLineElement(initialX, type, onUpdate, orderNum = null, onDelete = null) {
    const lineEl = document.createElement('div');
    lineEl.className = `split-line ${type}`;
    lineEl.style.left = `${initialX * 100}%`;

    // 如果有顺序编号，添加标签
    if (orderNum) {
        const label = document.createElement('div');
        label.className = 'split-line-label';
        label.textContent = orderNum;
        lineEl.appendChild(label);
    }

    // 添加删除按钮
    if (onDelete) {
        const deleteBtn = document.createElement('div');
        deleteBtn.className = 'split-line-delete';
        deleteBtn.textContent = '×';
        deleteBtn.addEventListener('mousedown', (e) => {
            e.stopPropagation();
            e.preventDefault();
        });
        deleteBtn.addEventListener('touchstart', (e) => {
            e.stopPropagation();
            e.preventDefault();
        }, { passive: false });
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            onDelete();
        });
        lineEl.appendChild(deleteBtn);
    }

    // 拖拽状态
    let isDragging = false;
    let startX = 0;
    let startLeft = 0;

    const onDragStart = (clientX) => {
        isDragging = true;
        startX = clientX;
        startLeft = parseFloat(lineEl.style.left);
        lineEl.classList.add('dragging');
    };

    const onDragMove = (clientX) => {
        if (!isDragging) return;

        const rect = elements.canvasWrapper.getBoundingClientRect();
        const deltaX = clientX - startX;
        const deltaPercent = (deltaX / rect.width) * 100;

        let newPercent = startLeft + deltaPercent;
        newPercent = Math.max(0, Math.min(newPercent, 100));

        lineEl.style.left = `${newPercent}%`;
        onUpdate(newPercent / 100);
    };

    const onDragEnd = () => {
        isDragging = false;
        lineEl.classList.remove('dragging');
    };

    // 鼠标事件
    const onMouseDown = (e) => {
        e.preventDefault();
        onDragStart(e.clientX);
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    };

    const onMouseMove = (e) => {
        if (!isDragging) return;
        e.preventDefault();
        onDragMove(e.clientX);
    };

    const onMouseUp = () => {
        onDragEnd();
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
    };

    // 触摸事件
    const onTouchStart = (e) => {
        if (e.touches.length !== 1) return;
        e.preventDefault();
        onDragStart(e.touches[0].clientX);
        document.addEventListener('touchmove', onTouchMove, { passive: false });
        document.addEventListener('touchend', onTouchEnd);
    };

    const onTouchMove = (e) => {
        if (!isDragging) return;
        e.preventDefault();
        onDragMove(e.touches[0].clientX);
    };

    const onTouchEnd = () => {
        onDragEnd();
        document.removeEventListener('touchmove', onTouchMove);
        document.removeEventListener('touchend', onTouchEnd);
    };

    lineEl.addEventListener('mousedown', onMouseDown);
    lineEl.addEventListener('touchstart', onTouchStart, { passive: false });

    elements.canvasWrapper.appendChild(lineEl);
}

/**
 * 设置分割线位置 (用于 AI 自动检测结果应用)
 */
export function setSplitPositions(splitPositions) {
    const config = getPageConfig(state.currentPage);

    // 清除现有分割线
    config.splitLines = [];

    // 添加新的分割线
    splitPositions.forEach(pos => {
        config.splitLines.push({ x: pos, type: 'split' });
    });

    // 至少保留一条分割线
    if (config.splitLines.length === 0) {
        config.splitLines.push({ x: 0.5, type: 'split' });
    }

    renderSplitLines();
}

/**
 * 设置分割线位置到指定页
 */
export function setSplitPositionsForPage(pageIndex, splitPositions, sealLinePos = null) {
    if (!state.pagesData[pageIndex]) {
        state.pagesData[pageIndex] = {
            splitLines: [],
            sealLine: null,
        };
    }
    state.pagesData[pageIndex].splitLines = splitPositions.map(pos => ({
        x: pos,
        type: 'split',
    }));
    if (state.pagesData[pageIndex].splitLines.length === 0) {
        state.pagesData[pageIndex].splitLines.push({ x: 0.5, type: 'split' });
    }

    // 设置 API 检测到的密封线（根据位置自动判断左侧或右侧）
    if (sealLinePos !== null && sealLinePos !== undefined) {
        const side = sealLinePos < 0.5 ? 'left' : 'right';
        state.pagesData[pageIndex].sealLine = { x: sealLinePos, type: side };
    }
}

/**
 * 切换密封线状态
 */
export function toggleSealLine() {
    const config = getPageConfig(state.currentPage);

    if (config.sealLine) {
        config.sealLine = null;
    } else {
        const isOdd = state.currentPage % 2 !== 0;
        if (isOdd) {
            config.sealLine = { x: 0.15, type: 'left' };
        } else {
            config.sealLine = { x: 0.85, type: 'right' };
        }
    }
    renderSplitLines();
}

/**
 * 重置为对半分割
 */
export function resetToHalf() {
    const config = getPageConfig(state.currentPage);
    config.splitLines = [{ x: 0.5, type: 'split' }];
    renderSplitLines();
}

/**
 * 设置为三栏分割
 */
export function setThreeColumn() {
    const config = getPageConfig(state.currentPage);
    config.splitLines = [
        { x: 0.33, type: 'split' },
        { x: 0.67, type: 'split' },
    ];
    renderSplitLines();
}

/**
 * 添加一条分割线
 */
export function addSplitLine() {
    const config = getPageConfig(state.currentPage);
    if (config.splitLines.length >= 3) return;  // 最多3条

    // 在现有分割线之间添加
    const lastX = config.splitLines[config.splitLines.length - 1].x;
    config.splitLines.push({ x: Math.min(lastX + 0.15, 0.9), type: 'split' });
    renderSplitLines();
}

/**
 * 移除最后一条分割线
 */
export function removeSplitLine() {
    const config = getPageConfig(state.currentPage);
    if (config.splitLines.length <= 1) return;

    config.splitLines.pop();
    renderSplitLines();
}

/**
 * 批量应用配置到同类页面
 */
export function applySplitToType() {
    const currentConfig = getPageConfig(state.currentPage);
    const isCurrentOdd = state.currentPage % 2 !== 0;
    const typeName = isCurrentOdd ? '奇数页' : '偶数页';

    if (confirm(`确定将当前配置应用到所有${typeName}吗？`)) {
        for (let i = 1; i <= state.totalPages; i++) {
            const isIterOdd = i % 2 !== 0;
            if (isIterOdd === isCurrentOdd) {
                state.pagesData[i] = JSON.parse(JSON.stringify(currentConfig));
            }
        }
        alert('已应用完成');
    }
}

/**
 * 批量应用配置到所有页面
 */
export function applySplitToAll() {
    const currentConfig = getPageConfig(state.currentPage);
    if (confirm(`确定将当前配置应用到所有 ${state.totalPages} 页吗？`)) {
        for (let i = 1; i <= state.totalPages; i++) {
            state.pagesData[i] = JSON.parse(JSON.stringify(currentConfig));
        }
        alert('已应用到所有页面');
    }
}