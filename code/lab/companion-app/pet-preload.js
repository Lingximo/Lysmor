const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('petHost', {
  moveBy: (dx, dy) => ipcRenderer.send('pet-move', { dx, dy }),
  setInteractive: (on) => ipcRenderer.send('pet-interactive', !!on),
  debug: (m) => ipcRenderer.send('pet-debug', String(m)),
  chat: (text) => ipcRenderer.invoke('pet-chat', text),
  playalong: (action) => ipcRenderer.invoke('pet-playalong', action),
  setVisible: (on) => ipcRenderer.send('pet-visible', !!on),
  companionState: () => ipcRenderer.invoke('pet-companion-state'),
  vitals: () => ipcRenderer.invoke('pet-vitals'),
  petLine: (kind) => ipcRenderer.invoke('pet-line', kind),
  onCursor: (cb) => ipcRenderer.on('pet-cursor', (_e, pt) => cb(pt)),
  onOpenChat: (cb) => ipcRenderer.on('pet-open-chat', () => cb()),
  hide: () => ipcRenderer.send('pet-hide'),
  quit: () => ipcRenderer.send('pet-quit'),
});
