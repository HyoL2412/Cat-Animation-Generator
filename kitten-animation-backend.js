// server.js
const express = require('express');
const cors = require('cors');
const fs = require('fs').promises;
const path = require('path');
const { createCanvas, loadImage } = require('canvas');
const GIFEncoder = require('gifencoder');
const ffmpeg = require('fluent-ffmpeg');
const ffmpegStatic = require('ffmpeg-static');
const { v4: uuidv4 } = require('uuid');

// Set ffmpeg path
ffmpeg.setFfmpegPath(ffmpegStatic);

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true, limit: '50mb' }));

// Create temp directory
const tempDir = path.join(__dirname, 'temp');
fs.mkdir(tempDir, { recursive: true }).catch(console.error);

// Root endpoint
app.get('/', (req, res) => {
    res.json({
        status: 'OK',
        message: 'Cute Kitten Animation Export Server',
        endpoints: {
            exportGif: 'POST /export-gif',
            exportVideo: 'POST /export-video'
        }
    });
});

// Helper function to clean base64 data
function cleanBase64(base64String) {
    return base64String.replace(/^data:image\/\w+;base64,/, '');
}

// Export GIF endpoint
app.post('/export-gif', async (req, res) => {
    const sessionId = uuidv4();
    const sessionDir = path.join(tempDir, sessionId);
    
    try {
        await fs.mkdir(sessionDir, { recursive: true });
        
        const { frames, width = 480, height = 360, delay = 250 } = req.body;
        
        if (!frames || !Array.isArray(frames) || frames.length === 0) {
            return res.status(400).json({ error: 'No frames provided' });
        }
        
        console.log(`Creating GIF with ${frames.length} frames...`);
        
        // Create GIF encoder
        const encoder = new GIFEncoder(width, height);
        const outputPath = path.join(sessionDir, 'animation.gif');
        const stream = require('fs').createWriteStream(outputPath);
        
        encoder.createReadStream().pipe(stream);
        encoder.start();
        encoder.setRepeat(0); // 0 = loop forever
        encoder.setDelay(delay);
        encoder.setQuality(10); // Best quality
        
        // Process each frame
        for (let i = 0; i < frames.length; i++) {
            console.log(`Processing frame ${i + 1}/${frames.length}`);
            
            const canvas = createCanvas(width, height);
            const ctx = canvas.getContext('2d');
            
            // Load and draw the frame
            const frameData = cleanBase64(frames[i]);
            const buffer = Buffer.from(frameData, 'base64');
            const image = await loadImage(buffer);
            
            ctx.drawImage(image, 0, 0, width, height);
            encoder.addFrame(ctx);
        }
        
        encoder.finish();
        
        // Wait for file to be written
        await new Promise(resolve => stream.on('finish', resolve));
        
        // Send the GIF file
        const gifBuffer = await fs.readFile(outputPath);
        res.set({
            'Content-Type': 'image/gif',
            'Content-Disposition': 'attachment; filename="cute-kitten-animation.gif"'
        });
        res.send(gifBuffer);
        
        // Cleanup
        setTimeout(async () => {
            try {
                await fs.rm(sessionDir, { recursive: true, force: true });
            } catch (err) {
                console.error('Cleanup error:', err);
            }
        }, 5000);
        
    } catch (error) {
        console.error('GIF export error:', error);
        res.status(500).json({ error: 'Failed to create GIF', details: error.message });
        
        // Cleanup on error
        try {
            await fs.rm(sessionDir, { recursive: true, force: true });
        } catch (err) {
            console.error('Cleanup error:', err);
        }
    }
});

// Export Video endpoint
app.post('/export-video', async (req, res) => {
    const sessionId = uuidv4();
    const sessionDir = path.join(tempDir, sessionId);
    
    try {
        await fs.mkdir(sessionDir, { recursive: true });
        
        const { 
            frames, 
            animationType = 'default',
            message = '',
            duration = 12,
            audioFiles = null,
            width = 480,
            height = 360
        } = req.body;
        
        if (!frames || !Array.isArray(frames) || frames.length === 0) {
            return res.status(400).json({ error: 'No frames provided' });
        }
        
        console.log(`Creating video with ${frames.length} frames, duration: ${duration}s`);
        
        // Save frames as images
        const framePaths = [];
        for (let i = 0; i < frames.length; i++) {
            const framePath = path.join(sessionDir, `frame_${String(i).padStart(4, '0')}.png`);
            const frameData = cleanBase64(frames[i]);
            await fs.writeFile(framePath, frameData, 'base64');
            framePaths.push(framePath);
        }
        
        const outputPath = path.join(sessionDir, 'animation.mp4');
        const frameRate = frames.length / duration;
        
        // Create video from frames
        await new Promise((resolve, reject) => {
            let command = ffmpeg()
                .input(path.join(sessionDir, 'frame_%04d.png'))
                .inputOptions([
                    '-framerate', String(frameRate),
                    '-pattern_type', 'sequence'
                ])
                .outputOptions([
                    '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p',
                    '-crf', '23',
                    '-preset', 'medium',
                    '-movflags', '+faststart'
                ])
                .output(outputPath);
            
            // Add audio if available (placeholder for now)
            // In a real implementation, you would download and merge audio files
            
            command
                .on('start', (commandLine) => {
                    console.log('FFmpeg command:', commandLine);
                })
                .on('progress', (progress) => {
                    console.log('Processing: ' + (progress.percent || 0).toFixed(2) + '% done');
                })
                .on('end', () => {
                    console.log('Video created successfully');
                    resolve();
                })
                .on('error', (err) => {
                    console.error('FFmpeg error:', err);
                    reject(err);
                })
                .run();
        });
        
        // Send the video file
        const videoBuffer = await fs.readFile(outputPath);
        res.set({
            'Content-Type': 'video/mp4',
            'Content-Disposition': `attachment; filename="cute-kitten-${animationType}.mp4"`
        });
        res.send(videoBuffer);
        
        // Cleanup
        setTimeout(async () => {
            try {
                await fs.rm(sessionDir, { recursive: true, force: true });
            } catch (err) {
                console.error('Cleanup error:', err);
            }
        }, 5000);
        
    } catch (error) {
        console.error('Video export error:', error);
        res.status(500).json({ error: 'Failed to create video', details: error.message });
        
        // Cleanup on error
        try {
            await fs.rm(sessionDir, { recursive: true, force: true });
        } catch (err) {
            console.error('Cleanup error:', err);
        }
    }
});

// Health check endpoint
app.get('/health', (req, res) => {
    res.json({ status: 'healthy', timestamp: new Date().toISOString() });
});

// Start server
app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
    console.log(`Local: http://localhost:${PORT}`);
});

// Graceful shutdown
process.on('SIGTERM', async () => {
    console.log('SIGTERM received, cleaning up...');
    try {
        await fs.rm(tempDir, { recursive: true, force: true });
    } catch (err) {
        console.error('Cleanup error:', err);
    }
    process.exit(0);
});