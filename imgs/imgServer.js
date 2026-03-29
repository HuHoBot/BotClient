const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

// 设置服务器端口
const PORT = 2087;

// 支持的图片格式
const imageExtensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'];

// 创建HTTP服务器
const server = http.createServer((req, res) => {
    // 解析请求URL
    const parsedUrl = url.parse(req.url);
    const pathname = decodeURIComponent(parsedUrl.pathname);
    
    // 获取文件路径（相对于当前目录）
    const filePath = path.join(process.cwd(), pathname);
    
    // 检查是否为根路径，列出目录下的图片文件
    if (pathname === '/' || pathname === '') {
        // 读取当前目录下的文件列表
        fs.readdir(process.cwd(), (err, files) => {
            if (err) {
                res.writeHead(500, { 'Content-Type': 'text/plain' });
                res.end('Internal Server Error');
                return;
            }
            
            // 过滤出图片文件
            const imageFiles = files.filter(file => {
                const ext = path.extname(file).toLowerCase();
                return imageExtensions.includes(ext);
            });
            
            // 生成HTML页面显示图片列表
            let html = '<html><head><title>Image Server</title></head><body>';
            html += '<h1>Available Images</h1><ul>';
            
            imageFiles.forEach(file => {
                html += `<li><a href="${file}">${file}</a></li>`;
            });
            
            html += '</ul></body></html>';
            
            res.writeHead(200, { 'Content-Type': 'text/html' });
            res.end(html);
        });
        return;
    }
    
    // 检查文件是否存在
    fs.access(filePath, fs.constants.F_OK, (err) => {
        if (err) {
            res.writeHead(404, { 'Content-Type': 'text/plain' });
            res.end('File not found');
            return;
        }
        
        // 检查是否为文件
        fs.stat(filePath, (err, stats) => {
            if (err || !stats.isFile()) {
                res.writeHead(404, { 'Content-Type': 'text/plain' });
                res.end('File not found');
                return;
            }
            
            // 检查文件扩展名是否为图片
            const ext = path.extname(filePath).toLowerCase();
            if (!imageExtensions.includes(ext)) {
                res.writeHead(403, { 'Content-Type': 'text/plain' });
                res.end('Access denied');
                return;
            }
            
            // 根据文件扩展名设置Content-Type
            const mimeTypes = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.bmp': 'image/bmp',
                '.webp': 'image/webp',
                '.svg': 'image/svg+xml'
            };
            
            // 设置响应头
            res.writeHead(200, {
                'Content-Type': mimeTypes[ext] || 'image/jpeg'
            });
            
            // 创建可读流并发送文件内容
            const fileStream = fs.createReadStream(filePath);
            fileStream.pipe(res);
            
            // 文件传输完成后删除文件
            res.on('finish', () => {
                fs.unlink(filePath, (unlinkErr) => {
                    if (unlinkErr) {
                        console.error(`Failed to delete file: ${filePath}`, unlinkErr);
                    } else {
                        console.log(`Image deleted: ${filePath}`);
                    }
                });
            });
            
            // 处理流错误
            fileStream.on('error', (streamErr) => {
                res.writeHead(500, { 'Content-Type': 'text/plain' });
                res.end('Error reading file');
            });
        });
    });
});

// 启动服务器
server.listen(PORT, () => {
    console.log(`Image server running at http://localhost:${PORT}/`);
});