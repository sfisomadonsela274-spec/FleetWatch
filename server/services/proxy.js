/**
 * FastAPI Gateway Reverse Proxy Service
 * Unifies all FastAPI compliance, reports, and streaming endpoints under the Node.js port 4000 gateway.
 */
export async function forwardToFastApi(req, res, targetPath) {
  const finalPath = targetPath || req.originalUrl;
  const upstreamBase = (process.env.FASTAPI_URL || 'http://127.0.0.1:8001').replace(/\/+$/, '');
  const targetUrl = `${upstreamBase}${finalPath}`;
  try {
    const headers = { ...req.headers };
    delete headers.host;
    delete headers['content-length'];

    const fetchOptions = {
      method: req.method,
      headers
    };

    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(req.method) && req.body && Object.keys(req.body).length > 0) {
      fetchOptions.body = JSON.stringify(req.body);
      headers['content-type'] = 'application/json';
    }

    const upstreamRes = await fetch(targetUrl, fetchOptions);

    res.status(upstreamRes.status);
    upstreamRes.headers.forEach((value, key) => {
      const lower = key.toLowerCase();
      if (!['transfer-encoding', 'connection', 'content-length'].includes(lower)) {
        res.setHeader(key, value);
      }
    });

    // Handle SSE event streams
    if (upstreamRes.headers.get('content-type')?.includes('text/event-stream')) {
      const reader = upstreamRes.body.getReader();
      req.on('close', () => reader.cancel());
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        res.write(value);
      }
      res.end();
      return;
    }

    const bodyBuffer = Buffer.from(await upstreamRes.arrayBuffer());
    res.send(bodyBuffer);
  } catch (err) {
    console.error(`[FastAPI Gateway Proxy Error] ${targetPath}: ${err.message}`);
    res.status(502).json({
      error: 'FastAPI reporting & compliance engine unavailable on port 8001',
      detail: err.message
    });
  }
}
