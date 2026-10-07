class CWidgetNeInterfaceDetail extends CWidget {
 setContents(response) {
  this.clearContents();
  const root = document.createElement('div');
  root.className = 'ne-widget';
  this._body.appendChild(root);
  const broadcast = (hostid, itemid) => {
   const data = { [CWidgetsData.DATA_TYPE_HOST_ID]: [String(hostid)] };
   if (itemid) data[CWidgetsData.DATA_TYPE_ITEM_ID] = [String(itemid)];
   this.broadcast(data);
  };
  this._ne_state ??= {};
  window.NEWidgetRuntime.render(root, response.ne_payload || {}, 'detail', broadcast, this._ne_state);
 }
}
