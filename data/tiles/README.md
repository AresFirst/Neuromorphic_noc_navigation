本目录用于放置离线杭州地图瓦片。

矢量瓦片推荐文件名：

- `hangzhou.mbtiles`
- 或 `hangzhou.pmtiles`

如果想在完全断网时保留 OpenStreetMap 标准样式，可以放置本地 OSM 栅格瓦片：

```text
data/tiles/osm/{z}/{x}/{y}.png
```

支持 `.png`、`.jpg`、`.jpeg` 和 `.webp`。完全断网使用时还需要准备：

```text
data/offline_map/assets/leaflet.js
data/offline_map/assets/leaflet.css
```

上述 Leaflet 文件只用于 Web GUI。PySide6 桌面 GUI 会直接用 Qt 读取
`data/tiles/osm`，不需要 Leaflet。

这些大文件默认被 `.gitignore` 忽略。Web GUI 会优先读取本地 `hangzhou.mbtiles`；
如果同时提供 `data/offline_map/assets/pmtiles.js`，也可以读取 `hangzhou.pmtiles`；
如果提供 `data/tiles/osm`，会读取本地 OSM 栅格瓦片。
