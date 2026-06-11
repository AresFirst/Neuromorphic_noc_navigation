本目录用于放置离线地图前端资源。

如果要完全断网并保留 OpenStreetMap 标准栅格样式，请准备：

- `leaflet.js`
- `leaflet.css`

如果要启用本地 MapLibre 矢量瓦片，请准备：

- `maplibre-gl.js`
- `maplibre-gl.css`
- 可选：`pmtiles.js`

缺少本地资源时，Web GUI 默认会使用在线 OpenStreetMap 标准底图。严格离线且缺少
Leaflet/OSM 栅格瓦片或 MapLibre/矢量瓦片时，才会使用 Canvas 降级渲染本地
GraphML 道路网络、SNN 路线、车辆、拥堵和波前图层。
