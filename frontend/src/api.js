/**
 * 后端 API 调用模块
 * 负责与 FastAPI 后端通信，进行版面分析
 */

const API_BASE = '/api';

/**
 * 检查后端 API 健康状态
 */
export async function checkApiHealth() {
    try {
        const response = await fetch(`${API_BASE}/health`);
        if (response.ok) {
            const data = await response.json();
            return data.status === 'ok';
        }
        return false;
    } catch {
        return false;
    }
}

/**
 * 上传 PDF 文件并进行版面分析
 * @param {File} file - PDF 文件
 * @param {number} numColumns - 期望的列数 (2 或 3)
 * @param {Function} onProgress - 进度回调 (current, total) => void
 * @returns {Promise<Object>} 分析结果
 */
export async function analyzePdf(file, numColumns = 0, onProgress = null) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('num_columns', numColumns);

    try {
        const response = await fetch(`${API_BASE}/analyze`, {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `服务器错误 (${response.status})`);
        }

        const result = await response.json();
        return result;
    } catch (error) {
        if (error.message?.includes('Failed to fetch')) {
            throw new Error('无法连接到 AI 后端服务，请确认后端已启动');
        }
        throw error;
    }
}

/**
 * 上传 PDF 文件并进行版面分析（SSE 流式进度版）
 * @param {File} file - PDF 文件
 * @param {number} numColumns - 期望的列数
 * @param {Object} callbacks - 回调函数集合
 * @param {Function} callbacks.onStart - (totalPages) => void
 * @param {Function} callbacks.onProgress - (data) => void
 * @returns {Promise<Object>} 分析结果
 */
export function analyzePdfSse(file, numColumns = 0, callbacks = {}) {
    return new Promise((resolve, reject) => {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('num_columns', numColumns);

        fetch(`${API_BASE}/analyze-sse`, {
            method: 'POST',
            body: formData,
        }).then(async (response) => {
            if (!response.ok) {
                reject(new Error(`服务器错误 (${response.status})`));
                return;
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            try {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });

                    const parts = buffer.split('\n\n');
                    buffer = parts.pop();

                    for (const part of parts) {
                        const lines = part.trim().split('\n');
                        let eventType = 'message';
                        let dataStr = '';

                        for (const line of lines) {
                            if (line.startsWith('event: ')) {
                                eventType = line.slice(7).trim();
                            } else if (line.startsWith('data: ')) {
                                dataStr = line.slice(6);
                            }
                        }

                        if (!dataStr) continue;

                        let data;
                        try {
                            data = JSON.parse(dataStr);
                        } catch {
                            data = dataStr;
                        }

                        switch (eventType) {
                            case 'start':
                                callbacks.onStart?.(data.total_pages);
                                break;
                            case 'progress':
                                callbacks.onProgress?.(data);
                                break;
                            case 'complete':
                                resolve(data);
                                break;
                            case 'error':
                                reject(new Error(data.message || '分析失败'));
                                break;
                        }
                    }
                }
            } catch (e) {
                reject(e);
            }
        }).catch((error) => {
            if (error.message?.includes('Failed to fetch')) {
                reject(new Error('无法连接到 AI 后端服务，请确认后端已启动'));
            } else {
                reject(error);
            }
        });
    });
}

/**
 * 上传图像文件并进行版面分析
 * @param {File} file - 图像文件
 * @param {number} numColumns - 期望的列数
 * @returns {Promise<Object>} 分析结果
 */
export async function analyzeImage(file, numColumns = 0) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('num_columns', numColumns);

    try {
        const response = await fetch(`${API_BASE}/analyze-image`, {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `服务器错误 (${response.status})`);
        }

        return await response.json();
    } catch (error) {
        if (error.message?.includes('Failed to fetch')) {
            throw new Error('无法连接到 AI 后端服务，请确认后端已启动');
        }
        throw error;
    }
}