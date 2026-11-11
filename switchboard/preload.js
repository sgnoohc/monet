const { contextBridge, ipcRenderer } = require('electron');

const EVENTS = new Set(['status', 'conversations', 'message', 'reaction', 'hotkey']);

contextBridge.exposeInMainWorld('sb', {
  platform: 'mac',
  getState: () => ipcRenderer.invoke('state:get'),
  fetchMessages: (key, before) => ipcRenderer.invoke('messages:fetch', key, before),
  send: (key, text) => ipcRenderer.invoke('messages:send', key, text),
  markRead: key => ipcRenderer.invoke('conv:markRead', key),
  react: (key, messageId, value, add) => ipcRenderer.invoke('messages:react', key, messageId, value, add),
  reactors: (key, messageId, reactionKey) => ipcRenderer.invoke('messages:reactors', key, messageId, reactionKey),
  searchGifs: query => ipcRenderer.invoke('gifs:search', query),
  upload: (key, files, text) => ipcRenderer.invoke('messages:upload', key, files, text),
  fetchMedia: (key, ref) => ipcRenderer.invoke('media:fetch', key, ref),
  openFile: (key, attachment) => ipcRenderer.invoke('file:open', key, attachment),
  setDiscordToken: token => ipcRenderer.invoke('discord:setToken', token),
  removeDiscord: () => ipcRenderer.invoke('discord:remove'),
  mattermostBrowserLogin: url => ipcRenderer.invoke('mattermost:browserLogin', url),
  setMattermostToken: (url, token) => ipcRenderer.invoke('mattermost:setToken', url, token),
  removeMattermost: () => ipcRenderer.invoke('mattermost:remove'),
  setWebApps: list => ipcRenderer.invoke('webapps:set', list),
  setView: view => ipcRenderer.invoke('view:set', view),
  addSlack: (userToken, appToken) => ipcRenderer.invoke('slack:add', userToken, appToken),
  removeSlack: id => ipcRenderer.invoke('slack:remove', id),
  popupMenu: items => ipcRenderer.invoke('menu:popup', items),
  copyText: text => ipcRenderer.send('clipboard:write', text),
  phoneSetupCode: part => ipcRenderer.invoke('phone:setupCode', part),
  setBadge: n => ipcRenderer.send('badge', n),
  focus: () => ipcRenderer.send('focus'),
  openExternal: url => ipcRenderer.send('open-external', url),
  on: (event, fn) => {
    if (EVENTS.has(event)) ipcRenderer.on(event, (_e, payload) => fn(payload));
  },
});
