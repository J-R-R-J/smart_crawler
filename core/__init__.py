# -*- coding: utf-8 -*-
"""SmartCrawler core 业务层。

封装：Browser（WebEngine + QWebChannel 桥）、CookieManager、Detector、
Extractor、Picker、Pager、PopupHandler 与抓取状态机 Crawler，
以及全局信号总线 signals.get_signals() 与用户偏好 UserPrefs。
"""
