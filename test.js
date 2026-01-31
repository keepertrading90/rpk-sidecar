console.log('Test starting...');

try {
    const electron = require('electron');
    console.log('Electron type:', typeof electron);
    console.log('Electron keys:', Object.keys(electron));

    if (electron.app) {
        console.log('App type:', typeof electron.app);
        console.log('App has whenReady:', typeof electron.app.whenReady);
    }
} catch (e) {
    console.error('Error:', e.message);
    console.error('Stack:', e.stack);
}

console.log('Test done');
