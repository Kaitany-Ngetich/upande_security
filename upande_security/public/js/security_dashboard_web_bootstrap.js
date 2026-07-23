(function () {
  "use strict";

  function isSecurityDashboardRoute() {
    var path = window.location.pathname.replace(/\/+$/, "");
    return path === "/security-dashboard";
  }

  function bootSecurityDashboard() {
    if (!isSecurityDashboardRoute()) {
      return;
    }

    var dashboardPage =
      window.frappe &&
      frappe.pages &&
      frappe.pages["security-dashboard"];

    if (
      !dashboardPage ||
      typeof dashboardPage.on_page_load !== "function"
    ) {
      console.error(
        "Security Dashboard scripts were loaded, but the page controller was not found."
      );
      return;
    }

    var root = document.getElementById(
      "security-dashboard-web-root"
    );

    if (!root) {
      root = document.createElement("div");
      root.id = "security-dashboard-web-root";

      var target =
        document.querySelector("main") ||
        document.querySelector(".page-content") ||
        document.body;

      target.appendChild(root);
    }

    if (root.dataset.securityDashboardLoaded !== "1") {
      dashboardPage.on_page_load(root);
      root.dataset.securityDashboardLoaded = "1";
    }

    if (
      typeof dashboardPage.on_page_show === "function"
    ) {
      dashboardPage.on_page_show(root);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      bootSecurityDashboard
    );
  } else {
    bootSecurityDashboard();
  }
})();
