import { jsPDF } from 'jspdf';
import { state } from './state.js';
import { elements } from './dom.js';
import { getPageConfig } from './editor.js';

/**
 * 导出质量等级配置
 * level: 0=低 1=中 2=高 3=原图
 */
const QUALITY_LEVELS = [
    { name: '低',   scale: 1.0, jpegQuality: 0.75, desc: '小文件，适合快速预览' },
    { name: '中',   scale: 2.0, jpegQuality: 0.92, desc: '平衡质量与文件大小，适合大多数场景' },
    { name: '高',   scale: 3.0, jpegQuality: 0.96, desc: '高清晰度，适合打印输出' },
    { name: '原图', scale: 4.0, jpegQuality: 0.98, desc: '原始分辨率，文件最大' },
];

export function getQualityConfig(level) {
    return QUALITY_LEVELS[level] || QUALITY_LEVELS[1];
}

/**
 * 导出处理后的 PDF
 * 支持多条分割线，将每一页切割成多个 A4 页面
 */
export async function exportPdf() {
    if (!state.pdfDoc && !state.fileData) return;

    elements.exportBtn.disabled = true;
    elements.exportBtn.textContent = '生成中...';

    const fit = elements.exportFitSelect ? elements.exportFitSelect.value : 'a4-fit';
    const qualityLevel = elements.qualitySlider ? parseInt(elements.qualitySlider.value) : 1;
    const qualityCfg = getQualityConfig(qualityLevel);

    try {
        let doc = null;

        for (let i = 1; i <= state.totalPages; i++) {
            const config = getPageConfig(i);

            let ranges = [];
            const splitLines = config.splitLines || [{ x: 0.5, type: 'split' }];
            const seal = config.sealLine;

            const sortedLines = [...splitLines].sort((a, b) => a.x - b.x);

            if (seal) {
                let effectiveStart = 0;
                let effectiveEnd = 1;

                if (seal.type === 'left') {
                    effectiveStart = seal.x;
                } else {
                    effectiveEnd = seal.x;
                }

                let prevX = effectiveStart;
                for (const line of sortedLines) {
                    if (line.x > effectiveStart && line.x < effectiveEnd) {
                        ranges.push([prevX, line.x]);
                        prevX = line.x;
                    }
                }
                ranges.push([prevX, effectiveEnd]);
            } else {
                let prevX = 0;
                for (const line of sortedLines) {
                    ranges.push([prevX, line.x]);
                    prevX = line.x;
                }
                ranges.push([prevX, 1]);
            }

            // 使用选定的渲染倍率
            let sourceCanvas;
            if (state.isPdf) {
                const page = await state.pdfDoc.getPage(i);
                const viewport = page.getViewport({ scale: qualityCfg.scale });
                sourceCanvas = document.createElement('canvas');
                sourceCanvas.width = viewport.width;
                sourceCanvas.height = viewport.height;
                await page.render({
                    canvasContext: sourceCanvas.getContext('2d'),
                    viewport
                }).promise;
            } else {
                const img = new Image();
                img.src = state.fileData;
                await new Promise(r => img.onload = r);
                sourceCanvas = document.createElement('canvas');
                sourceCanvas.width = img.width;
                sourceCanvas.height = img.height;
                sourceCanvas.getContext('2d').drawImage(img, 0, 0);
            }

            for (let rng of ranges) {
                const startXRatio = rng[0];
                const endXRatio = rng[1];
                const widthRatio = endXRatio - startXRatio;

                if (widthRatio <= 0.01) continue;

                const sx = sourceCanvas.width * startXRatio;
                const sy = 0;
                const sWidth = sourceCanvas.width * widthRatio;
                const sHeight = sourceCanvas.height;

                const sliceCanvas = document.createElement('canvas');
                sliceCanvas.width = sWidth;
                sliceCanvas.height = sHeight;
                sliceCanvas.getContext('2d').drawImage(
                    sourceCanvas, sx, sy, sWidth, sHeight, 0, 0, sWidth, sHeight
                );

                const imgData = sliceCanvas.toDataURL('image/jpeg', qualityCfg.jpegQuality);

                let pageWidth, pageHeight, orientation;
                let drawX, drawY, drawW, drawH;

                if (fit === 'wysiwyg') {
                    pageHeight = 297;
                    pageWidth = pageHeight * (sWidth / sHeight);
                    orientation = pageWidth > pageHeight ? 'landscape' : 'portrait';
                    drawX = 0; drawY = 0; drawW = pageWidth; drawH = pageHeight;
                } else {
                    pageWidth = 210; pageHeight = 297; orientation = 'portrait';
                    if (fit === 'a4-fill') {
                        drawX = 0; drawY = 0; drawW = 210; drawH = 297;
                    } else {
                        const sliceAspect = sWidth / sHeight;
                        const a4Aspect = 210 / 297;
                        if (sliceAspect > a4Aspect) {
                            drawW = 210; drawH = 210 / sliceAspect;
                        } else {
                            drawH = 297; drawW = 297 * sliceAspect;
                        }
                        drawX = (210 - drawW) / 2;
                        drawY = (297 - drawH) / 2;
                    }
                }

                if (!doc) {
                    doc = new jsPDF({ unit: 'mm', orientation, format: [pageWidth, pageHeight] });
                } else {
                    doc.addPage([pageWidth, pageHeight], orientation);
                }

                doc.addImage(imgData, 'JPEG', drawX, drawY, drawW, drawH);
            }
        }

        if (!doc) {
            alert('没有可导出的内容');
            return;
        }
        doc.save(`${state.fileName}(A4).pdf`);

    } catch (e) {
        console.error(e);
        alert('导出失败: ' + e.message);
    } finally {
        elements.exportBtn.disabled = false;
        elements.exportBtn.innerHTML = '<span class="material-icons">save_alt</span> 导出为 PDF (A4)';
    }
}