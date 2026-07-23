(function () {
  window.frappe = window.frappe || {};
  frappe.pages = frappe.pages || {};
  frappe.ui = frappe.ui || {};

  function asJQuery(element) {
    if (window.jQuery) {
      return window.jQuery(element);
    }

    return element;
  }

  function createButton(container, label, handler, className) {
    var button = document.createElement("button");

    button.type = "button";
    button.className =
      className || "btn btn-default btn-sm";
    button.textContent = label;

    if (typeof handler === "function") {
      button.addEventListener("click", handler);
    }

    container.appendChild(button);
    return asJQuery(button);
  }

  frappe.ui.make_app_page = function (options) {
    options = options || {};

    var parent = options.parent;

    if (parent && parent.jquery) {
      parent = parent.get(0);
    }

    if (!parent) {
      throw new Error(
        "Security dashboard website wrapper was not found."
      );
    }

    parent.innerHTML = [
      '<div class="page-container security-web-page">',
      '  <div class="page-head security-web-page-head">',
      '    <div class="container-fluid">',
      '      <div class="row">',
      '        <div class="col">',
      '          <h1 class="page-title"></h1>',
      '          <div class="page-subtitle"></div>',
      '        </div>',
      '        <div class="col-auto page-actions"></div>',
      '      </div>',
      '    </div>',
      '  </div>',
      '  <div class="page-body">',
      '    <div class="container-fluid">',
      '      <div class="layout-main-section"></div>',
      '    </div>',
      '  </div>',
      '</div>'
    ].join("");

    var titleElement =
      parent.querySelector(".page-title");

    var subtitleElement =
      parent.querySelector(".page-subtitle");

    var actionElement =
      parent.querySelector(".page-actions");

    var mainElement =
      parent.querySelector(".layout-main-section");

    titleElement.textContent =
      options.title || "Security Command Centre";

    var page = {
      wrapper: asJQuery(parent),
      main: asJQuery(mainElement),
      body: asJQuery(mainElement),
      page: asJQuery(parent),

      set_title: function (title) {
        titleElement.textContent = title || "";
      },

      set_subtitle: function (subtitle) {
        subtitleElement.textContent = subtitle || "";
      },

      set_indicator: function (label) {
        subtitleElement.textContent = label || "";
      },

      set_primary_action: function (label, handler) {
        return createButton(
          actionElement,
          label,
          handler,
          "btn btn-primary btn-sm"
        );
      },

      set_secondary_action: function (label, handler) {
        return createButton(
          actionElement,
          label,
          handler,
          "btn btn-default btn-sm"
        );
      },

      add_inner_button: function (label, handler) {
        return createButton(
          actionElement,
          label,
          handler,
          "btn btn-default btn-sm"
        );
      },

      add_menu_item: function (label, handler) {
        return createButton(
          actionElement,
          label,
          handler,
          "btn btn-default btn-sm"
        );
      },

      add_action_item: function (label, handler) {
        return createButton(
          actionElement,
          label,
          handler,
          "btn btn-default btn-sm"
        );
      },

      clear_actions: function () {
        actionElement.innerHTML = "";
      },

      hide_menu: function () {},
      show_menu: function () {},
      hide_form: function () {},
      show_form: function () {},
      add_field: function () {
        return null;
      }
    };

    return page;
  };

  if (!frappe.set_route) {
    frappe.set_route = function () {
      var parts = Array.prototype.slice.call(arguments);

      if (!parts.length) {
        return;
      }

      window.location.href =
        "/app/" +
        parts
          .map(function (part) {
            return encodeURIComponent(part);
          })
          .join("/");
    };
  }
})();
