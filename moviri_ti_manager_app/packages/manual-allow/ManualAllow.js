/******/ (() => {
    // webpackBootstrap
    /******/ "use strict";
    /******/ // The require scope
    /******/    const e = {};
    /******/
    /************************************************************************/
    /******/ /* webpack/runtime/compat get default export */
    /******/    (() => {
        /******/ // getDefaultExport function for compatibility with non-harmony modules
        /******/ e.n = t => {
            /******/ const r = t && t.__esModule ? 
            /******/ () => t["default"] : 
            /******/ () => t;
            /******/            e.d(r, {
                a: r
            });
            /******/            return r;
            /******/        };
        /******/    })();
    /******/
    /******/ /* webpack/runtime/define property getters */
    /******/    (() => {
        /******/ // define getter/value functions for harmony exports
        /******/ e.d = (t, r) => {
            /******/ if (Array.isArray(r)) {
                /******/ var n = 0;
                /******/                while (n < r.length) {
                    /******/ var a = r[n++];
                    /******/                    var o = r[n++];
                    /******/                    if (!e.o(t, a)) {
                        /******/ if (o === 0) {
                            /******/ Object.defineProperty(t, a, {
                                enumerable: true,
                                value: r[n++]
                            });
                            /******/                        } else {
                            /******/ Object.defineProperty(t, a, {
                                enumerable: true,
                                get: o
                            });
                            /******/                        }
                        /******/                    } else if (o === 0) {
                        n++;
                    }
                    /******/                }
                /******/            } else {
                /******/ for (var a in r) {
                    /******/ if (e.o(r, a) && !e.o(t, a)) {
                        /******/ Object.defineProperty(t, a, {
                            enumerable: true,
                            get: r[a]
                        });
                        /******/                    }
                    /******/                }
                /******/            }
            /******/        };
        /******/    })();
    /******/
    /******/ /* webpack/runtime/hasOwnProperty shorthand */
    /******/    (() => {
        /******/ e.o = (e, t) => Object.prototype.hasOwnProperty.call(e, t)
        /******/;
    })();
    /******/
    /******/ /* webpack/runtime/make namespace object */
    /******/    (() => {
        /******/ // define __esModule on exports
        /******/ e.r = e => {
            /******/ if (Symbol.toStringTag) {
                /******/ Object.defineProperty(e, Symbol.toStringTag, {
                    value: "Module"
                });
                /******/            }
            /******/            Object.defineProperty(e, "__esModule", {
                value: true
            });
            /******/        };
        /******/    })();
    /******/
    /************************************************************************/    let t = {};
    // ESM COMPAT FLAG
        e.r(t);
    // EXPORTS
        e.d(t, {
        default: () => /* binding */ ae
    });
    // external "react"
    const r = require("react");
    var n =  e.n(r);
    // external "@splunk/react-ui/Button"
    const a = require("@splunk/react-ui/Button");
    var o =  e.n(a);
    // external "@splunk/react-ui/Text"
    const l = require("@splunk/react-ui/Text");
    var i =  e.n(l);
    // external "@splunk/react-ui/Table"
    const c = require("@splunk/react-ui/Table");
    var u =  e.n(c);
    // external "@splunk/react-ui/Select"
    const s = require("@splunk/react-ui/Select");
    var f =  e.n(s);
    // external "@splunk/react-ui/Paginator"
    const d = require("@splunk/react-ui/Paginator");
    var p =  e.n(d);
    // external "@splunk/react-ui/Heading"
    const m = require("@splunk/react-ui/Heading");
    var v =  e.n(m);
    // external "@splunk/react-ui/WaitSpinner"
    const y = require("@splunk/react-ui/WaitSpinner");
    var h =  e.n(y);
    // external "@splunk/splunk-utils/fetch"
    const g = require("@splunk/splunk-utils/fetch");
    // external "styled-components"
    const b = require("styled-components");
    var w =  e.n(b);
    // external "@splunk/themes"
    const x = require("@splunk/themes");
    // ./src/ManualAllowStyles.ts
    var E, S;
    function k(e, t) {
        return t || (t = e.slice(0)), Object.freeze(Object.defineProperties(e, {
            raw: {
                value: Object.freeze(t)
            }
        }));
    }
    var C = w().div(E || (E = k([ "\n    ", ";\n    width: 100%;\n    box-sizing: border-box;\n    font-size: ", ";\n    line-height: 200%;\n    margin: ", " 0;\n    padding: ", " ", ";\n\n    border-radius: ", ";\n    box-shadow: ", ";\n    background-color: ", ";\n" ])), x.mixins.reset("block"), x.variables.fontSizeLarge, x.variables.spacingLarge, x.variables.spacingLarge, x.variables.spacingXXLarge, x.variables.borderRadius, x.variables.overlayShadow, x.variables.backgroundColorSection);
    var O = w().div(S || (S = k([ "\n    font-weight: bold;\n    color: ", ";\n    font-size: ", ";\n" ])), x.variables.brandColor, x.variables.fontSizeXXLarge);
    // ./src/ManualAllow.tsx
    function P(e) {
        "@babel/helpers - typeof";
        return P = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function(e) {
            return typeof e;
        } : function(e) {
            return e && "function" == typeof Symbol && e.constructor === Symbol && e !== Symbol.prototype ? "symbol" : typeof e;
        }, P(e);
    }
    function j(e, t) {
        var r = "undefined" != typeof Symbol && e[Symbol.iterator] || e["@@iterator"];
        if (!r) {
            if (Array.isArray(e) || (r = B(e)) || t && e && "number" == typeof e.length) {
                r && (e = r);
                var n = 0, a = function e() {};
                return {
                    s: a,
                    n: function t() {
                        return n >= e.length ? {
                            done: !0
                        } : {
                            done: !1,
                            value: e[n++]
                        };
                    },
                    e: function e(t) {
                        throw t;
                    },
                    f: a
                };
            }
            throw new TypeError("Invalid attempt to iterate non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.");
        }
        var o, l = !0, i = !1;
        return {
            s: function t() {
                r = r.call(e);
            },
            n: function e() {
                var t = r.next();
                return l = t.done, t;
            },
            e: function e(t) {
                i = !0, o = t;
            },
            f: function e() {
                try {
                    l || null == r["return"] || r["return"]();
                } finally {
                    if (i) throw o;
                }
            }
        };
    }
    function T(e) {
        return D(e) || I(e) || B(e) || A();
    }
    function A() {
        throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.");
    }
    function I(e) {
        if ("undefined" != typeof Symbol && null != e[Symbol.iterator] || null != e["@@iterator"]) return Array.from(e);
    }
    function D(e) {
        if (Array.isArray(e)) return H(e);
    }
    function _() {
        /*! regenerator-runtime -- Copyright (c) 2014-present, Facebook, Inc. -- license (MIT): https://github.com/babel/babel/blob/main/packages/babel-helpers/LICENSE */ var e, t, r = "function" == typeof Symbol ? Symbol : {}, n = r.iterator || "@@iterator", a = r.toStringTag || "@@toStringTag";
        function o(r, n, a, o) {
            var c = n && n.prototype instanceof i ? n : i, u = Object.create(c.prototype);
            return N(u, "_invoke", function(r, n, a) {
                var o, i, c, u = 0, s = a || [], f = !1, d = {
                    p: 0,
                    n: 0,
                    v: e,
                    a: p,
                    f: p.bind(e, 4),
                    d: function t(r, n) {
                        return o = r, i = 0, c = e, d.n = n, l;
                    }
                };
                function p(r, n) {
                    for (i = r, c = n, t = 0; !f && u && !a && t < s.length; t++) {
                        var a, o = s[t], p = d.p, m = o[2];
                        r > 3 ? (a = m === n) && (c = o[(i = o[4]) ? 5 : (i = 3, 3)], o[4] = o[5] = e) : o[0] <= p && ((a = r < 2 && p < o[1]) ? (i = 0, 
                        d.v = n, d.n = o[1]) : p < m && (a = r < 3 || o[0] > n || n > m) && (o[4] = r, o[5] = n, 
                        d.n = m, i = 0));
                    }
                    if (a || r > 1) return l;
                    throw f = !0, n;
                }
                return function(a, s, m) {
                    if (u > 1) throw TypeError("Generator is already running");
                    for (f && 1 === s && p(s, m), i = s, c = m; (t = i < 2 ? e : c) || !f; ) {
                        o || (i ? i < 3 ? (i > 1 && (d.n = -1), p(i, c)) : d.n = c : d.v = c);
                        try {
                            if (u = 2, o) {
                                if (i || (a = "next"), t = o[a]) {
                                    if (!(t = t.call(o, c))) throw TypeError("iterator result is not an object");
                                    if (!t.done) return t;
                                    c = t.value, i < 2 && (i = 0);
                                } else 1 === i && (t = o["return"]) && t.call(o), i < 2 && (c = TypeError("The iterator does not provide a '" + a + "' method"), 
                                i = 1);
                                o = e;
                            } else if ((t = (f = d.n < 0) ? c : r.call(n, d)) !== l) break;
                        } catch (t) {
                            o = e, i = 1, c = t;
                        } finally {
                            u = 1;
                        }
                    }
                    return {
                        value: t,
                        done: f
                    };
                };
            }(r, a, o), !0), u;
        }
        var l = {};
        function i() {}
        function c() {}
        function u() {}
        t = Object.getPrototypeOf;
        var s = [][n] ? t(t([][n]())) : (N(t = {}, n, function() {
            return this;
        }), t), f = u.prototype = i.prototype = Object.create(s);
        function d(e) {
            return Object.setPrototypeOf ? Object.setPrototypeOf(e, u) : (e.__proto__ = u, N(e, a, "GeneratorFunction")), 
            e.prototype = Object.create(f), e;
        }
        return c.prototype = u, N(f, "constructor", u), N(u, "constructor", c), c.displayName = "GeneratorFunction", 
        N(u, a, "GeneratorFunction"), N(f), N(f, a, "Generator"), N(f, n, function() {
            return this;
        }), N(f, "toString", function() {
            return "[object Generator]";
        }), (_ = function e() {
            return {
                w: o,
                m: d
            };
        })();
    }
    function N(e, t, r, n) {
        var a = Object.defineProperty;
        try {
            a({}, "", {});
        } catch (e) {
            a = 0;
        }
        N = function e(t, r, n, o) {
            function l(e, r) {
                N(t, e, function(t) {
                    return this._invoke(e, r, t);
                });
            }
            r ? a ? a(t, r, {
                value: n,
                enumerable: !o,
                configurable: !o,
                writable: !o
            }) : t[r] = n : (l("next", 0), l("throw", 1), l("return", 2));
        }, N(e, t, r, n);
    }
    function L(e, t, r, n, a, o, l) {
        try {
            var i = e[o](l), c = i.value;
        } catch (e) {
            return void r(e);
        }
        i.done ? t(c) : Promise.resolve(c).then(n, a);
    }
    function F(e) {
        return function() {
            var t = this, r = arguments;
            return new Promise(function(n, a) {
                var o = e.apply(t, r);
                function l(e) {
                    L(o, n, a, l, i, "next", e);
                }
                function i(e) {
                    L(o, n, a, l, i, "throw", e);
                }
                l(void 0);
            });
        };
    }
    function z(e, t) {
        return U(e) || M(e, t) || B(e, t) || R();
    }
    function R() {
        throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.");
    }
    function B(e, t) {
        if (e) {
            if ("string" == typeof e) return H(e, t);
            var r = {}.toString.call(e).slice(8, -1);
            return "Object" === r && e.constructor && (r = e.constructor.name), "Map" === r || "Set" === r ? Array.from(e) : "Arguments" === r || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(r) ? H(e, t) : void 0;
        }
    }
    function H(e, t) {
        (null == t || t > e.length) && (t = e.length);
        for (var r = 0, n = Array(t); r < t; r++) n[r] = e[r];
        return n;
    }
    function M(e, t) {
        var r = null == e ? null : "undefined" != typeof Symbol && e[Symbol.iterator] || e["@@iterator"];
        if (null != r) {
            var n, a, o, l, i = [], c = !0, u = !1;
            try {
                if (o = (r = r.call(e)).next, 0 === t) {
                    if (Object(r) !== r) return;
                    c = !1;
                } else for (;!(c = (n = o.call(r)).done) && (i.push(n.value), i.length !== t); c = !0) ;
            } catch (e) {
                u = !0, a = e;
            } finally {
                try {
                    if (!c && null != r["return"] && (l = r["return"](), Object(l) !== l)) return;
                } finally {
                    if (u) throw a;
                }
            }
            return i;
        }
    }
    function U(e) {
        if (Array.isArray(e)) return e;
    }
    function W(e, t) {
        var r = Object.keys(e);
        if (Object.getOwnPropertySymbols) {
            var n = Object.getOwnPropertySymbols(e);
            t && (n = n.filter(function(t) {
                return Object.getOwnPropertyDescriptor(e, t).enumerable;
            })), r.push.apply(r, n);
        }
        return r;
    }
    function q(e) {
        for (var t = 1; t < arguments.length; t++) {
            var r = null != arguments[t] ? arguments[t] : {};
            t % 2 ? W(Object(r), !0).forEach(function(t) {
                K(e, t, r[t]);
            }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(r)) : W(Object(r)).forEach(function(t) {
                Object.defineProperty(e, t, Object.getOwnPropertyDescriptor(r, t));
            });
        }
        return e;
    }
    function K(e, t, r) {
        return (t = G(t)) in e ? Object.defineProperty(e, t, {
            value: r,
            enumerable: !0,
            configurable: !0,
            writable: !0
        }) : e[t] = r, e;
    }
    function G(e) {
        var t = J(e, "string");
        return "symbol" == P(t) ? t : t + "";
    }
    function J(e, t) {
        if ("object" != P(e) || !e) return e;
        var r = e[Symbol.toPrimitive];
        if (void 0 !== r) {
            var n = r.call(e, t || "default");
            if ("object" != P(n)) return n;
            throw new TypeError("@@toPrimitive must return a primitive value.");
        }
        return ("string" === t ? String : Number)(e);
    }
    var X = "moviri_ti_manager_app";
    var $ = "manual_allowlist";
    var V = window.location.pathname.split("/")[1] || "en-US";
    var Q = "/".concat(V, "/splunkd/__raw/servicesNS/nobody/").concat(X, "/storage/collections/data/").concat($);
    var Y = function e(t) {
        var r = arguments.length > 1 && arguments[1] !== undefined ? arguments[1] : {};
        return fetch(t, q(q(q({}, g.defaultFetchInit), r), {}, {
            headers: q(q({}, g.defaultFetchInit.headers), r.headers)
        }));
    };
    var Z = function e(t) {
        var r = "(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9][0-9]|[0-9])";
        var n = new RegExp("^".concat(r, "\\.").concat(r, "\\.").concat(r, "\\.").concat(r, "\\/([0-9]|[1-2][0-9]|3[0-2])$"));
        return n.test(t);
    };
    var ee = function e(t) {
        return t.split(/[\s,;]+/).map(function(e) {
            return e.trim();
        }).filter(function(e) {
            return e.length > 0;
        }).map(function(e) {
            return e.includes("/") ? e : "".concat(e, "/32");
        });
    };
    var te = function e(t) {
        if (!t) return "-";
        var r = new Date(t);
        return isNaN(r.getTime()) ? "-" : r.toLocaleString();
    };
    var re = function e(t, r) {
        if (r === "never") return "";
        var n = new Date;
        var a = parseInt(t, 10) || 0;
        if (a <= 0) return "";
        if (r === "m") n.setMinutes(n.getMinutes() + a);
        if (r === "h") n.setHours(n.getHours() + a);
        if (r === "d") n.setDate(n.getDate() + a);
        return n.toISOString();
    };
    var ne = function e() {
        var t = (0, r.useState)([]), a = z(t, 2), l = a[0], c = a[1];
        var s = (0, r.useState)(""), d = z(s, 2), m = d[0], y = d[1];
        var g = (0, r.useState)(""), b = z(g, 2), w = b[0], x = b[1];
        var E = (0, r.useState)(""), S = z(E, 2), k = S[0], P = S[1];
        var A = (0, r.useState)("Both (F5+PaloAlto)"), I = z(A, 2), D = I[0], N = I[1];
        var L = (0, r.useState)("24"), R = z(L, 2), B = R[0], H = R[1];
        var M = (0, r.useState)("h"), U = z(M, 2), W = U[0], q = U[1];
        var K = (0, r.useState)(false), G = z(K, 2), J = G[0], X = G[1];
        var $ = (0, r.useState)(true), ne = z($, 2), ae = ne[0], oe = ne[1];
        var le = (0, r.useState)(null), ie = z(le, 2), ce = ie[0], ue = ie[1];
        var se = (0, r.useState)(""), fe = z(se, 2), de = fe[0], pe = fe[1];
        var me = (0, r.useState)(1), ve = z(me, 2), ye = ve[0], he = ve[1];
        var ge = (0, r.useState)(10), be = z(ge, 2), we = be[0], xe = be[1];
        var Ee = (0, r.useState)("none"), Se = z(Ee, 2), ke = Se[0], Ce = Se[1];
        var Oe = (0, r.useState)("none"), Pe = z(Oe, 2), je = Pe[0], Te = Pe[1];
        var Ae = (0, r.useState)([]), Ie = z(Ae, 2), De = Ie[0], _e = Ie[1];
        var Ne = (0, r.useRef)(null);
        (0, r.useEffect)(function() {
            var e =  function() {
                var e = F( _().m(function e() {
                    var t, r, n, a, o;
                    return _().w(function(e) {
                        while (1) switch (e.p = e.n) {
                          case 0:
                            e.p = 0;
                            e.n = 1;
                            return Y("/".concat(V, "/splunkd/__raw/services/authentication/current-context?output_mode=json"));

                          case 1:
                            t = e.v;
                            if (!t.ok) {
                                e.n = 3;
                                break;
                            }
                            e.n = 2;
                            return t.json();

                          case 2:
                            n = e.v;
                            a = (n === null || n === void 0 || (r = n.entry) === null || r === void 0 || (r = r[0]) === null || r === void 0 || (r = r.content) === null || r === void 0 ? void 0 : r.username) || "Unknown";
                            x(a);

                          case 3:
                            e.n = 5;
                            break;

                          case 4:
                            e.p = 4;
                            o = e.v;
                            console.error("Unable to get current user:", o);

                          case 5:
                            return e.a(2);
                        }
                    }, e, null, [ [ 0, 4 ] ]);
                }));
                return function t() {
                    return e.apply(this, arguments);
                };
            }();
            e();
            Le();
        }, []);
        (0, r.useEffect)(function() {
            he(1);
            _e([]);
        }, [ de, l.length, we, ke, je ]);
        var Le =  function() {
            var e = F( _().m(function e() {
                var t, r, n, a, o, l, i, u;
                return _().w(function(e) {
                    while (1) switch (e.p = e.n) {
                      case 0:
                        X(true);
                        ue(null);
                        e.p = 1;
                        t = [];
                        r = 0;
                        n = 5e4;
                        a = true;

                      case 2:
                        if (!a) {
                            e.n = 7;
                            break;
                        }
                        e.n = 3;
                        return Y("".concat(Q, "?limit=").concat(n, "&skip=").concat(r));

                      case 3:
                        o = e.v;
                        if (o.ok) {
                            e.n = 5;
                            break;
                        }
                        e.n = 4;
                        return o.text();

                      case 4:
                        l = e.v;
                        throw new Error("Failed to fetch chunk at skip ".concat(r, " (").concat(o.status, "): ").concat(l));

                      case 5:
                        e.n = 6;
                        return o.json();

                      case 6:
                        i = e.v;
                        t = [].concat(T(t), T(i));
                        if (i.length < n) {
                            a = false;
                        } else {
                            r += n;
                        }
                        e.n = 2;
                        break;

                      case 7:
                        c(t);
                        e.n = 9;
                        break;

                      case 8:
                        e.p = 8;
                        u = e.v;
                        ue("Network error while fetching data: ".concat(u.message || String(u)));

                      case 9:
                        e.p = 9;
                        X(false);
                        oe(false);
                        return e.f(9);

                      case 10:
                        return e.a(2);
                    }
                }, e, null, [ [ 1, 8, 9, 10 ] ]);
            }));
            return function t() {
                return e.apply(this, arguments);
            };
        }();
        // --- KPI Computations ---
                var Fe = l.length;
        var ze = l.filter(function(e) {
            return !e.expirydate;
        }).length;
        var Re = (0, r.useMemo)(function() {
            var e = 0;
            var t = 0;
            l.forEach(function(r) {
                if (r.expirydate && r.timestamp) {
                    var n = new Date(r.timestamp).getTime();
                    var a = new Date(r.expirydate).getTime();
                    if (!isNaN(n) && !isNaN(a) && a > n) {
                        e += a - n;
                        t++;
                    }
                }
            });
            if (t === 0) return "N/A";
            var r = e / t / (1e3 * 60 * 60);
            if (r < 1) return "".concat((r * 60).toFixed(0), " Mins");
            if (r > 24) return "".concat((r / 24).toFixed(1), " Days");
            return "".concat(r.toFixed(1), " Hours");
        }, [ l ]);
        var Be = (0, r.useMemo)(function() {
            var e = {};
            l.forEach(function(t) {
                if (t.source) {
                    if (!e[t.source]) {
                        e[t.source] = {
                            source: t.source,
                            count: 0,
                            user: t.user,
                            timestamp: t.timestamp,
                            keys: []
                        };
                    }
                    e[t.source].count += 1;
                    e[t.source].keys.push(t._key);
                }
            });
            return Object.values(e).sort(function(e, t) {
                return new Date(t.timestamp).getTime() - new Date(e.timestamp).getTime();
            });
        }, [ l ]);
        var He = l.filter(function(e) {
            var t = de.toLowerCase();
            return e.ip.toLowerCase().includes(t) || e.user && e.user.toLowerCase().includes(t) || e.reason && e.reason.toLowerCase().includes(t) || e.source && e.source.toLowerCase().includes(t) || e.target && e.target.toLowerCase().includes(t);
        });
        var Me = T(He).sort(function(e, t) {
            if (je === "none" || ke === "none") return 0;
            var r = (e[ke] || "").toLowerCase();
            var n = (t[ke] || "").toLowerCase();
            if (r < n) return je === "asc" ? -1 : 1;
            if (r > n) return je === "asc" ? 1 : -1;
            return 0;
        });
        var Ue = Math.max(1, Math.ceil(Me.length / we));
        var We = Me.slice((ye - 1) * we, ye * we);
        var qe = We.length > 0 && We.every(function(e) {
            return De.includes(e._key);
        });
        var Ke = function e() {
            var t = We.map(function(e) {
                return e._key;
            });
            if (qe) {
                _e(function(e) {
                    return e.filter(function(e) {
                        return !t.includes(e);
                    });
                });
            } else {
                var r = new Set([].concat(T(De), T(t)));
                _e(Array.from(r));
            }
        };
        var Ge = function e(t) {
            _e(function(e) {
                return e.includes(t) ? e.filter(function(e) {
                    return e !== t;
                }) : [].concat(T(e), [ t ]);
            });
        };
        var Je = function e(t, r) {
            var n = r.sortKey;
            if (ke === n) {
                Te(function(e) {
                    return e === "asc" ? "desc" : e === "desc" ? "none" : "asc";
                });
                if (je === "desc") Ce("none");
            } else {
                Ce(n);
                Te("asc");
            }
        };
        var Xe = (0, r.useMemo)(function() {
            return ee(m);
        }, [ m ]);
        var $e = Xe.length === 0;
        var Ve = Xe.length > 20;
        var Qe = $e || Xe.every(Z);
        var Ye = Xe.some(function(e) {
            return l.some(function(t) {
                return t.ip === e;
            });
        });
        var Ze = W === "never" || !isNaN(Number(B)) && Number(B) > 0;
        var et =  function() {
            var e = F( _().m(function e() {
                var t, r, n, a, o, l, i, c, u, s;
                return _().w(function(e) {
                    while (1) switch (e.p = e.n) {
                      case 0:
                        if (!(!Qe || Ye || Ve || $e || !Ze)) {
                            e.n = 1;
                            break;
                        }
                        return e.a(2);

                      case 1:
                        ue(null);
                        X(true);
                        t = (new Date).toISOString();
                        r = re(B, W);
                        n = Xe.map(function(e) {
                            return {
                                _key: e,
                                ip: e,
                                user: w.trim() || "Unknown",
                                reason: k.trim() || "No reason provided",
                                timestamp: t,
                                expirydate: r,
                                target: D
                            };
                        });
                        e.p = 2;
                        if (!(n.length === 1)) {
                            e.n = 6;
                            break;
                        }
                        e.n = 3;
                        return Y(Q, {
                            method: "POST",
                            headers: {
                                "Content-Type": "application/json"
                            },
                            body: JSON.stringify(n[0])
                        });

                      case 3:
                        a = e.v;
                        if (a.ok) {
                            e.n = 5;
                            break;
                        }
                        l = Error;
                        e.n = 4;
                        return a.text();

                      case 4:
                        i = e.v;
                        throw new l(i);

                      case 5:
                        e.n = 9;
                        break;

                      case 6:
                        e.n = 7;
                        return Y("".concat(Q, "/batch_save"), {
                            method: "POST",
                            headers: {
                                "Content-Type": "application/json"
                            },
                            body: JSON.stringify(n)
                        });

                      case 7:
                        o = e.v;
                        if (o.ok) {
                            e.n = 9;
                            break;
                        }
                        c = Error;
                        e.n = 8;
                        return o.text();

                      case 8:
                        u = e.v;
                        throw new c(u);

                      case 9:
                        y("");
                        P("");
                        e.n = 10;
                        return Le();

                      case 10:
                        e.n = 12;
                        break;

                      case 11:
                        e.p = 11;
                        s = e.v;
                        ue("Network error while saving: ".concat(s.message || String(s)));
                        X(false);

                      case 12:
                        return e.a(2);
                    }
                }, e, null, [ [ 2, 11 ] ]);
            }));
            return function t() {
                return e.apply(this, arguments);
            };
        }();
        var tt =  function() {
            var e = F( _().m(function e(t) {
                var r, n, a, o, l, i, c;
                return _().w(function(e) {
                    while (1) switch (e.p = e.n) {
                      case 0:
                        r = false;
                        n = 100;
                        a = 0;

                      case 1:
                        if (!(a < t.length)) {
                            e.n = 6;
                            break;
                        }
                        o = t.slice(a, a + n);
                        l = JSON.stringify({
                            _key: {
                                $in: o
                            }
                        });
                        e.p = 2;
                        e.n = 3;
                        return Y("".concat(Q, "?query=").concat(encodeURIComponent(l)), {
                            method: "DELETE"
                        });

                      case 3:
                        i = e.v;
                        if (!i.ok) {
                            r = true;
                            console.error("Failed to batch delete chunk starting at index ".concat(a));
                        }
                        e.n = 5;
                        break;

                      case 4:
                        e.p = 4;
                        c = e.v;
                        r = true;
                        console.error("Network error on batch delete for chunk starting at index ".concat(a, ":"), c);

                      case 5:
                        a += n;
                        e.n = 1;
                        break;

                      case 6:
                        return e.a(2, r);
                    }
                }, e, null, [ [ 2, 4 ] ]);
            }));
            return function t(r) {
                return e.apply(this, arguments);
            };
        }();
        var rt =  function() {
            var e = F( _().m(function e() {
                var t;
                return _().w(function(e) {
                    while (1) switch (e.n) {
                      case 0:
                        if (!(De.length === 0)) {
                            e.n = 1;
                            break;
                        }
                        return e.a(2);

                      case 1:
                        ue(null);
                        X(true);
                        e.n = 2;
                        return tt(De);

                      case 2:
                        t = e.v;
                        if (t) ue("Some selected items could not be deleted successfully. Check console logs.");
                        _e([]);
                        e.n = 3;
                        return Le();

                      case 3:
                        return e.a(2);
                    }
                }, e);
            }));
            return function t() {
                return e.apply(this, arguments);
            };
        }();
        var nt =  function() {
            var e = F( _().m(function e(t) {
                var r;
                return _().w(function(e) {
                    while (1) switch (e.n) {
                      case 0:
                        if (!(t.length === 0)) {
                            e.n = 1;
                            break;
                        }
                        return e.a(2);

                      case 1:
                        ue(null);
                        X(true);
                        e.n = 2;
                        return tt(t);

                      case 2:
                        r = e.v;
                        if (r) ue("Some items from the list could not be deleted successfully. Check console logs.");
                        _e(function(e) {
                            return e.filter(function(e) {
                                return !t.includes(e);
                            });
                        });
                        e.n = 3;
                        return Le();

                      case 3:
                        return e.a(2);
                    }
                }, e);
            }));
            return function t(r) {
                return e.apply(this, arguments);
            };
        }();
        var at = function e(t) {
            var r;
            var n = (r = t.target.files) === null || r === void 0 ? void 0 : r[0];
            if (!n) return;
            var a = n.name;
            var o = new FileReader;
            o.onload =  function() {
                var e = F( _().m(function e(t) {
                    var r;
                    var n;
                    return _().w(function(e) {
                        while (1) switch (e.n) {
                          case 0:
                            n = (r = t.target) === null || r === void 0 ? void 0 : r.result;
                            if (!n) {
                                e.n = 1;
                                break;
                            }
                            e.n = 1;
                            return ot(n, a);

                          case 1:
                            if (Ne.current) {
                                Ne.current.value = "";
                            }

                          case 2:
                            return e.a(2);
                        }
                    }, e);
                }));
                return function(t) {
                    return e.apply(this, arguments);
                };
            }();
            o.readAsText(n);
        };
        var ot =  function() {
            var e = F( _().m(function e(t, r) {
                var n, a, o, i, c, u, s, f, d, p, m, v, y, h, g, b, x;
                return _().w(function(e) {
                    while (1) switch (e.p = e.n) {
                      case 0:
                        ue(null);
                        X(true);
                        n = t.split(/\r?\n/).map(function(e) {
                            return e.trim();
                        }).filter(function(e) {
                            return e.length > 0;
                        });
                        if (!(n.length === 0)) {
                            e.n = 1;
                            break;
                        }
                        ue("The selected file is empty or contains no valid data.");
                        X(false);
                        return e.a(2);

                      case 1:
                        a = (new Date).toISOString();
                        o = re(B, W);
                        i = n.map(function(e) {
                            var t, n, l;
                            var i = e.split(",");
                            var c = ((t = i[0]) === null || t === void 0 ? void 0 : t.trim()) || "";
                            var u = c.includes("/") ? c : "".concat(c, "/32");
                            return {
                                _key: u,
                                ip: u,
                                user: ((n = i[1]) === null || n === void 0 ? void 0 : n.trim()) || w.trim() || "Unknown",
                                reason: ((l = i[2]) === null || l === void 0 ? void 0 : l.trim()) || k.trim() || "Bulk upload",
                                timestamp: a,
                                expirydate: o,
                                source: r,
                                target: D
                            };
                        });
                        c = i.filter(function(e) {
                            return !Z(e.ip);
                        });
                        if (!(c.length > 0)) {
                            e.n = 2;
                            break;
                        }
                        ue("Upload blocked: Found ".concat(c.length, ' invalid CIDR formats (e.g., "').concat(c[0].ip, '"). Ensure file format is IP,User,Reason.'));
                        X(false);
                        return e.a(2);

                      case 2:
                        u = new Set(l.map(function(e) {
                            return e.ip;
                        }));
                        s = [];
                        f = new Set;
                        d = j(i);
                        try {
                            for (d.s(); !(p = d.n()).done; ) {
                                m = p.value;
                                if (!u.has(m.ip) && !f.has(m.ip)) {
                                    s.push(m);
                                    f.add(m.ip);
                                }
                            }
                        } catch (e) {
                            d.e(e);
                        } finally {
                            d.f();
                        }
                        if (!(s.length === 0)) {
                            e.n = 3;
                            break;
                        }
                        ue("All the IPs in this file are already present in the allowlist. No new IPs were added.");
                        X(false);
                        return e.a(2);

                      case 3:
                        v = 1e3;
                        y = false;
                        h = 0;

                      case 4:
                        if (!(h < s.length)) {
                            e.n = 9;
                            break;
                        }
                        g = s.slice(h, h + v);
                        e.p = 5;
                        e.n = 6;
                        return Y("".concat(Q, "/batch_save"), {
                            method: "POST",
                            headers: {
                                "Content-Type": "application/json"
                            },
                            body: JSON.stringify(g)
                        });

                      case 6:
                        b = e.v;
                        if (!b.ok) {
                            y = true;
                            console.error("Failed to save chunk starting at index ".concat(h));
                        }
                        e.n = 8;
                        break;

                      case 7:
                        e.p = 7;
                        x = e.v;
                        y = true;
                        console.error("Network error on chunk starting at index ".concat(h, ":"), x);

                      case 8:
                        h += v;
                        e.n = 4;
                        break;

                      case 9:
                        if (y) {
                            ue("Some batches were not saved successfully. Check the console logs for details.");
                        }
                        e.n = 10;
                        return Le();

                      case 10:
                        return e.a(2);
                    }
                }, e, null, [ [ 5, 7 ] ]);
            }));
            return function t(r, n) {
                return e.apply(this, arguments);
            };
        }();
        var lt = {
            flex: 1,
            minWidth: "250px",
            padding: "20px",
            backgroundColor: "#ffffff",
            borderRadius: "8px",
            border: "1px solid #e1e6eb",
            boxShadow: "0 2px 4px rgba(0,0,0,0.05)",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center"
        };
        var it = {
            fontSize: "13px",
            color: "#656d76",
            textTransform: "uppercase",
            fontWeight: 600,
            marginBottom: "8px"
        };
        var ct = {
            fontSize: "28px",
            fontWeight: "bold",
            color: "#1e252b"
        };
        
        return n().createElement(C, null, J && !ae &&  n().createElement("div", {
            style: {
                position: "fixed",
                top: 0,
                left: 0,
                width: "100vw",
                height: "100vh",
                backgroundColor: "rgba(255, 255, 255, 0.75)",
                zIndex: 9999,
                display: "flex",
                flexDirection: "column",
                justifyContent: "center",
                alignItems: "center"
            }
        },  n().createElement(h(), {
            size: "large"
        }),  n().createElement(v(), {
            level: 3,
            style: {
                marginTop: "20px",
                color: "#1e252b"
            }
        }, "Processing Operation..."),  n().createElement("div", {
            style: {
                color: "#656d76",
                marginTop: "10px",
                fontSize: "14px"
            }
        }, "Please wait while the KV Store updates. This may take a few moments for large files.")), ae ?  n().createElement("div", {
            style: {
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                height: "60vh"
            }
        },  n().createElement(h(), {
            size: "large"
        }),  n().createElement(v(), {
            level: 3,
            style: {
                marginTop: "25px",
                color: "#656d76"
            }
        }, "Loading Manual Allowlist..."),  n().createElement("div", {
            style: {
                color: "#8c959f",
                marginTop: "10px"
            }
        }, "Fetching Allowed IPs from KV Store. This might take a moment.")) :  n().createElement(n().Fragment, null,  n().createElement(O, {
            "data-testid": "greeting",
            style: {
                marginBottom: "20px"
            }
        }, "Threat Intelligence IP Allowlist"), ce &&  n().createElement("div", {
            style: {
                backgroundColor: "#fcdcdc",
                color: "#d30909",
                padding: "12px",
                borderRadius: "4px",
                marginBottom: "20px",
                border: "1px solid #d30909",
                fontSize: "14px"
            }
        },  n().createElement("strong", null, "Error:"), " ", ce),  n().createElement("div", {
            style: {
                display: "flex",
                gap: "20px",
                flexWrap: "wrap",
                marginBottom: "30px"
            }
        },  n().createElement("div", {
            style: lt
        },  n().createElement("div", {
            style: it
        }, "Total Active Allows"),  n().createElement("div", {
            style: ct
        }, Fe)),  n().createElement("div", {
            style: lt
        },  n().createElement("div", {
            style: it
        }, "Average Allow Duration"),  n().createElement("div", {
            style: ct
        }, Re)),  n().createElement("div", {
            style: lt
        },  n().createElement("div", {
            style: it
        }, "Permanent Allows"),  n().createElement("div", {
            style: ct
        }, ze, " ",  n().createElement("span", {
            style: {
                fontSize: "14px",
                fontWeight: "normal",
                color: "#656d76"
            }
        }, "IPs never expire")))),  n().createElement("div", {
            style: {
                backgroundColor: "#f8f9fa",
                padding: "20px",
                borderRadius: "8px",
                border: "1px solid #e1e6eb",
                marginBottom: "30px"
            }
        },  n().createElement(v(), {
            level: 4,
            style: {
                marginTop: 0,
                marginBottom: "15px"
            }
        }, "Add to Allowlist"),  n().createElement("div", {
            style: {
                display: "flex",
                gap: "15px",
                alignItems: "center",
                flexWrap: "wrap"
            }
        },  n().createElement(i(), {
            value: m,
            onChange: function e(t, r) {
                var n = r.value;
                return y(n);
            },
            placeholder: "IPs (comma separated, max 20)",
            error: !Qe || Ye || Ve,
            style: {
                width: "220px"
            }
        }),  n().createElement(i(), {
            value: k,
            onChange: function e(t, r) {
                var n = r.value;
                return P(n);
            },
            placeholder: "Reason (Optional)",
            style: {
                width: "200px"
            }
        }),  n().createElement("div", {
            style: {
                display: "flex",
                alignItems: "center",
                gap: "8px",
                borderLeft: "1px solid #ccc",
                paddingLeft: "15px"
            }
        },  n().createElement("span", {
            style: {
                fontSize: "14px",
                fontWeight: 500,
                color: "#3C444D"
            }
        }, "Target:"),  n().createElement(f(), {
            value: D,
            onChange: function e(t, r) {
                return N(r.value);
            },
            style: {
                width: "160px"
            },
            disabled: J
        },  n().createElement(f().Option, {
            label: "Both (F5+PaloAlto)",
            value: "Both (F5+PaloAlto)"
        }),  n().createElement(f().Option, {
            label: "F5",
            value: "F5"
        }),  n().createElement(f().Option, {
            label: "PaloAlto",
            value: "PaloAlto"
        }))),  n().createElement("div", {
            style: {
                display: "flex",
                alignItems: "center",
                gap: "8px",
                borderLeft: "1px solid #ccc",
                paddingLeft: "15px"
            }
        },  n().createElement("span", {
            style: {
                fontSize: "14px",
                fontWeight: 500,
                color: "#3C444D"
            }
        }, "Duration:"),  n().createElement(i(), {
            value: B,
            onChange: function e(t, r) {
                var n = r.value;
                return H(n);
            },
            disabled: W === "never" || J,
            error: !Ze,
            style: {
                width: "50px"
            }
        }),  n().createElement(f(), {
            value: W,
            onChange: function e(t, r) {
                return q(r.value);
            },
            style: {
                width: "100px"
            },
            disabled: J
        },  n().createElement(f().Option, {
            label: "Minutes",
            value: "m"
        }),  n().createElement(f().Option, {
            label: "Hours",
            value: "h"
        }),  n().createElement(f().Option, {
            label: "Days",
            value: "d"
        }),  n().createElement(f().Option, {
            label: "Never",
            value: "never"
        }))),  n().createElement(o(), {
            label: "Add IP(s)",
            appearance: "primary",
            onClick: et,
            disabled: $e || !Qe || Ye || Ve || !Ze || J,
            style: {
                marginLeft: "auto"
            }
        }),  n().createElement("div", {
            style: {
                borderLeft: "1px solid #ccc",
                height: "30px"
            }
        }),  n().createElement("input", {
            type: "file",
            accept: ".txt,.csv",
            ref: Ne,
            style: {
                display: "none"
            },
            onChange: at
        }),  n().createElement(o(), {
            label: "Bulk Upload",
            appearance: "secondary",
            onClick: function e() {
                var t;
                return (t = Ne.current) === null || t === void 0 ? void 0 : t.click();
            },
            disabled: J || !Ze
        })), !Qe && !Ve &&  n().createElement("div", {
            style: {
                color: "#d30909",
                fontSize: "12px",
                marginTop: "8px"
            }
        }, "Invalid format. Ensure IPs are valid (e.g., 192.168.1.1 or 10.0.0.0/24)."), !Ze &&  n().createElement("div", {
            style: {
                color: "#d30909",
                fontSize: "12px",
                marginTop: "8px"
            }
        }, "Please enter a valid number greater than 0 for the duration."), Ve &&  n().createElement("div", {
            style: {
                color: "#d30909",
                fontSize: "12px",
                marginTop: "8px",
                fontWeight: "bold"
            }
        }, "Max 20 IPs allowed manually. For larger sets, please use Bulk Upload."), Qe && Ye &&  n().createElement("div", {
            style: {
                color: "#d30909",
                fontSize: "12px",
                fontWeight: "bold",
                marginTop: "8px"
            }
        }, "One or more entered IPs are already in the allowlist.")), Be.length > 0 &&  n().createElement("div", {
            style: {
                marginBottom: "30px"
            }
        },  n().createElement(v(), {
            level: 4,
            style: {
                marginTop: 0,
                marginBottom: "15px"
            }
        }, "Uploaded Lists Management"),  n().createElement("div", {
            style: {
                border: "1px solid #e1e6eb",
                borderRadius: "8px",
                overflow: "hidden"
            }
        },  n().createElement(u(), {
            stripeRows: true
        },  n().createElement(u().Head, null,  n().createElement(u().HeadCell, null, "File Name"),  n().createElement(u().HeadCell, null, "Subnets Count"),  n().createElement(u().HeadCell, null, "Uploaded By"),  n().createElement(u().HeadCell, null, "Date"),  n().createElement(u().HeadCell, {
            style: {
                width: "180px"
            }
        }, "Actions")),  n().createElement(u().Body, null, Be.map(function(e) {
            
            return n().createElement(u().Row, {
                key: e.source
            },  n().createElement(u().Cell, {
                style: {
                    fontWeight: "bold"
                }
            }, e.source),  n().createElement(u().Cell, null, e.count),  n().createElement(u().Cell, null, e.user),  n().createElement(u().Cell, null, te(e.timestamp)),  n().createElement(u().Cell, null,  n().createElement(o(), {
                label: "Remove Entire List",
                appearance: "destructive",
                onClick: function t() {
                    return nt(e.keys);
                },
                disabled: J
            })));
        }))))),  n().createElement(v(), {
            level: 4,
            style: {
                marginTop: 0,
                marginBottom: "15px"
            }
        }, "All Allowed IPs"),  n().createElement("div", {
            style: {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "15px"
            }
        },  n().createElement(i(), {
            value: de,
            onChange: function e(t, r) {
                var n = r.value;
                return pe(n);
            },
            placeholder: "Search by IP, Target, User, Source, or Reason...",
            canClear: true,
            style: {
                width: "350px"
            }
        }),  n().createElement("div", {
            style: {
                display: "flex",
                alignItems: "center",
                gap: "15px"
            }
        }, De.length > 0 &&  n().createElement(o(), {
            label: "Delete Selected (".concat(De.length, ")"),
            appearance: "destructive",
            onClick: rt,
            disabled: J
        }),  n().createElement("div", {
            style: {
                borderLeft: "1px solid #ccc",
                height: "20px"
            }
        }),  n().createElement("span", {
            style: {
                fontSize: "14px",
                color: "#3C444D",
                fontWeight: 500
            }
        }, "Rows per page:"),  n().createElement(f(), {
            value: we,
            onChange: function e(t, r) {
                return xe(r.value);
            },
            style: {
                width: "80px"
            }
        },  n().createElement(f().Option, {
            label: "5",
            value: 5
        }),  n().createElement(f().Option, {
            label: "10",
            value: 10
        }),  n().createElement(f().Option, {
            label: "25",
            value: 25
        }),  n().createElement(f().Option, {
            label: "50",
            value: 50
        })))),  n().createElement("div", {
            style: {
                border: "1px solid #e1e6eb",
                borderRadius: "8px",
                overflow: "hidden"
            }
        },  n().createElement(u(), {
            stripeRows: true
        },  n().createElement(u().Head, null,  n().createElement(u().HeadCell, {
            style: {
                width: "40px",
                textAlign: "center"
            }
        },  n().createElement("input", {
            type: "checkbox",
            checked: qe,
            onChange: Ke,
            disabled: We.length === 0,
            style: {
                cursor: "pointer",
                width: "16px",
                height: "16px"
            },
            title: "Select all on this page"
        })),  n().createElement(u().HeadCell, {
            onSort: Je,
            sortKey: "ip",
            sortDir: ke === "ip" ? je : "none"
        }, "IP Address (CIDR)"),  n().createElement(u().HeadCell, {
            onSort: Je,
            sortKey: "target",
            sortDir: ke === "target" ? je : "none"
        }, "Target"),  n().createElement(u().HeadCell, {
            onSort: Je,
            sortKey: "source",
            sortDir: ke === "source" ? je : "none"
        }, "Source"),  n().createElement(u().HeadCell, {
            onSort: Je,
            sortKey: "user",
            sortDir: ke === "user" ? je : "none"
        }, "Submitted By"),  n().createElement(u().HeadCell, {
            onSort: Je,
            sortKey: "reason",
            sortDir: ke === "reason" ? je : "none"
        }, "Reason"),  n().createElement(u().HeadCell, {
            onSort: Je,
            sortKey: "timestamp",
            sortDir: ke === "timestamp" ? je : "none"
        }, "Allowed On"),  n().createElement(u().HeadCell, {
            onSort: Je,
            sortKey: "expirydate",
            sortDir: ke === "expirydate" ? je : "none"
        }, "Expiry Date")),  n().createElement(u().Body, null, We.length === 0 ?  n().createElement(u().Row, null,  n().createElement(u().Cell, {
            colSpan: 8,
            style: {
                textAlign: "center",
                padding: "30px",
                color: "#656d76"
            }
        }, J ? "Loading data..." : de ? "No IPs match your search." : "No IPs found in the allowlist.")) : We.map(function(e) {
            
            return n().createElement(u().Row, {
                key: e._key
            },  n().createElement(u().Cell, {
                style: {
                    textAlign: "center"
                }
            },  n().createElement("input", {
                type: "checkbox",
                checked: De.includes(e._key),
                onChange: function t() {
                    return Ge(e._key);
                },
                style: {
                    cursor: "pointer",
                    width: "16px",
                    height: "16px"
                }
            })),  n().createElement(u().Cell, {
                style: {
                    fontFamily: "monospace",
                    fontSize: "14px"
                }
            }, e.ip),  n().createElement(u().Cell, null, e.target || "Both (F5+PaloAlto)"),  n().createElement(u().Cell, null, e.source || "Manual Entry"),  n().createElement(u().Cell, null, e.user || "Unknown"),  n().createElement(u().Cell, null, e.reason || "-"),  n().createElement(u().Cell, null, te(e.timestamp)),  n().createElement(u().Cell, {
                style: {
                    fontWeight: "bold",
                    color: e.expirydate ? "#656d76" : "#28a745"
                }
            }, e.expirydate ? te(e.expirydate) : "Never"));
        })))), Ue > 1 &&  n().createElement("div", {
            style: {
                display: "flex",
                justifyContent: "center",
                marginTop: "20px"
            }
        },  n().createElement(p(), {
            current: ye,
            totalPages: Ue,
            onChange: function e(t, r) {
                var n = r.page;
                return he(n);
            }
        }))));
    };
    /* harmony default export */    const ae = ne;
    module.exports = t;
    /******/})();