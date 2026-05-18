/******************************************************************************
Copyright (c) Microsoft Corporation.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.
***************************************************************************** */
/* global Reflect, Promise, SuppressedError, Symbol, Iterator */


function __decorate(decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
}

typeof SuppressedError === "function" ? SuppressedError : function (error, suppressed, message) {
    var e = new Error(message);
    return e.name = "SuppressedError", e.error = error, e.suppressed = suppressed, e;
};

/**
 * @license
 * Copyright 2019 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const t$1=globalThis,e$2=t$1.ShadowRoot&&(void 0===t$1.ShadyCSS||t$1.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,s$2=Symbol(),o$4=new WeakMap;let n$3 = class n{constructor(t,e,o){if(this._$cssResult$=true,o!==s$2)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e;}get styleSheet(){let t=this.o;const s=this.t;if(e$2&&void 0===t){const e=void 0!==s&&1===s.length;e&&(t=o$4.get(s)),void 0===t&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),e&&o$4.set(s,t));}return t}toString(){return this.cssText}};const r$4=t=>new n$3("string"==typeof t?t:t+"",void 0,s$2),i$3=(t,...e)=>{const o=1===t.length?t[0]:e.reduce((e,s,o)=>e+(t=>{if(true===t._$cssResult$)return t.cssText;if("number"==typeof t)return t;throw Error("Value passed to 'css' function must be a 'css' function result: "+t+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(s)+t[o+1],t[0]);return new n$3(o,t,s$2)},S$1=(s,o)=>{if(e$2)s.adoptedStyleSheets=o.map(t=>t instanceof CSSStyleSheet?t:t.styleSheet);else for(const e of o){const o=document.createElement("style"),n=t$1.litNonce;void 0!==n&&o.setAttribute("nonce",n),o.textContent=e.cssText,s.appendChild(o);}},c$2=e$2?t=>t:t=>t instanceof CSSStyleSheet?(t=>{let e="";for(const s of t.cssRules)e+=s.cssText;return r$4(e)})(t):t;

/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */const{is:i$2,defineProperty:e$1,getOwnPropertyDescriptor:h$1,getOwnPropertyNames:r$3,getOwnPropertySymbols:o$3,getPrototypeOf:n$2}=Object,a$1=globalThis,c$1=a$1.trustedTypes,l$1=c$1?c$1.emptyScript:"",p$1=a$1.reactiveElementPolyfillSupport,d$1=(t,s)=>t,u$1={toAttribute(t,s){switch(s){case Boolean:t=t?l$1:null;break;case Object:case Array:t=null==t?t:JSON.stringify(t);}return t},fromAttribute(t,s){let i=t;switch(s){case Boolean:i=null!==t;break;case Number:i=null===t?null:Number(t);break;case Object:case Array:try{i=JSON.parse(t);}catch(t){i=null;}}return i}},f$1=(t,s)=>!i$2(t,s),b$1={attribute:true,type:String,converter:u$1,reflect:false,useDefault:false,hasChanged:f$1};Symbol.metadata??=Symbol("metadata"),a$1.litPropertyMetadata??=new WeakMap;let y$1 = class y extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t);}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,s=b$1){if(s.state&&(s.attribute=false),this._$Ei(),this.prototype.hasOwnProperty(t)&&((s=Object.create(s)).wrapped=true),this.elementProperties.set(t,s),!s.noAccessor){const i=Symbol(),h=this.getPropertyDescriptor(t,i,s);void 0!==h&&e$1(this.prototype,t,h);}}static getPropertyDescriptor(t,s,i){const{get:e,set:r}=h$1(this.prototype,t)??{get(){return this[s]},set(t){this[s]=t;}};return {get:e,set(s){const h=e?.call(this);r?.call(this,s),this.requestUpdate(t,h,i);},configurable:true,enumerable:true}}static getPropertyOptions(t){return this.elementProperties.get(t)??b$1}static _$Ei(){if(this.hasOwnProperty(d$1("elementProperties")))return;const t=n$2(this);t.finalize(),void 0!==t.l&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties);}static finalize(){if(this.hasOwnProperty(d$1("finalized")))return;if(this.finalized=true,this._$Ei(),this.hasOwnProperty(d$1("properties"))){const t=this.properties,s=[...r$3(t),...o$3(t)];for(const i of s)this.createProperty(i,t[i]);}const t=this[Symbol.metadata];if(null!==t){const s=litPropertyMetadata.get(t);if(void 0!==s)for(const[t,i]of s)this.elementProperties.set(t,i);}this._$Eh=new Map;for(const[t,s]of this.elementProperties){const i=this._$Eu(t,s);void 0!==i&&this._$Eh.set(i,t);}this.elementStyles=this.finalizeStyles(this.styles);}static finalizeStyles(s){const i=[];if(Array.isArray(s)){const e=new Set(s.flat(1/0).reverse());for(const s of e)i.unshift(c$2(s));}else void 0!==s&&i.push(c$2(s));return i}static _$Eu(t,s){const i=s.attribute;return  false===i?void 0:"string"==typeof i?i:"string"==typeof t?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=false,this.hasUpdated=false,this._$Em=null,this._$Ev();}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this));}addController(t){(this._$EO??=new Set).add(t),void 0!==this.renderRoot&&this.isConnected&&t.hostConnected?.();}removeController(t){this._$EO?.delete(t);}_$E_(){const t=new Map,s=this.constructor.elementProperties;for(const i of s.keys())this.hasOwnProperty(i)&&(t.set(i,this[i]),delete this[i]);t.size>0&&(this._$Ep=t);}createRenderRoot(){const t=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return S$1(t,this.constructor.elementStyles),t}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(true),this._$EO?.forEach(t=>t.hostConnected?.());}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.());}attributeChangedCallback(t,s,i){this._$AK(t,i);}_$ET(t,s){const i=this.constructor.elementProperties.get(t),e=this.constructor._$Eu(t,i);if(void 0!==e&&true===i.reflect){const h=(void 0!==i.converter?.toAttribute?i.converter:u$1).toAttribute(s,i.type);this._$Em=t,null==h?this.removeAttribute(e):this.setAttribute(e,h),this._$Em=null;}}_$AK(t,s){const i=this.constructor,e=i._$Eh.get(t);if(void 0!==e&&this._$Em!==e){const t=i.getPropertyOptions(e),h="function"==typeof t.converter?{fromAttribute:t.converter}:void 0!==t.converter?.fromAttribute?t.converter:u$1;this._$Em=e;const r=h.fromAttribute(s,t.type);this[e]=r??this._$Ej?.get(e)??r,this._$Em=null;}}requestUpdate(t,s,i,e=false,h){if(void 0!==t){const r=this.constructor;if(false===e&&(h=this[t]),i??=r.getPropertyOptions(t),!((i.hasChanged??f$1)(h,s)||i.useDefault&&i.reflect&&h===this._$Ej?.get(t)&&!this.hasAttribute(r._$Eu(t,i))))return;this.C(t,s,i);} false===this.isUpdatePending&&(this._$ES=this._$EP());}C(t,s,{useDefault:i,reflect:e,wrapped:h},r){i&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,r??s??this[t]),true!==h||void 0!==r)||(this._$AL.has(t)||(this.hasUpdated||i||(s=void 0),this._$AL.set(t,s)),true===e&&this._$Em!==t&&(this._$Eq??=new Set).add(t));}async _$EP(){this.isUpdatePending=true;try{await this._$ES;}catch(t){Promise.reject(t);}const t=this.scheduleUpdate();return null!=t&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(const[t,s]of this._$Ep)this[t]=s;this._$Ep=void 0;}const t=this.constructor.elementProperties;if(t.size>0)for(const[s,i]of t){const{wrapped:t}=i,e=this[s];true!==t||this._$AL.has(s)||void 0===e||this.C(s,void 0,i,e);}}let t=false;const s=this._$AL;try{t=this.shouldUpdate(s),t?(this.willUpdate(s),this._$EO?.forEach(t=>t.hostUpdate?.()),this.update(s)):this._$EM();}catch(s){throw t=false,this._$EM(),s}t&&this._$AE(s);}willUpdate(t){}_$AE(t){this._$EO?.forEach(t=>t.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=true,this.firstUpdated(t)),this.updated(t);}_$EM(){this._$AL=new Map,this.isUpdatePending=false;}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return  true}update(t){this._$Eq&&=this._$Eq.forEach(t=>this._$ET(t,this[t])),this._$EM();}updated(t){}firstUpdated(t){}};y$1.elementStyles=[],y$1.shadowRootOptions={mode:"open"},y$1[d$1("elementProperties")]=new Map,y$1[d$1("finalized")]=new Map,p$1?.({ReactiveElement:y$1}),(a$1.reactiveElementVersions??=[]).push("2.1.2");

/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */
const t=globalThis,i$1=t=>t,s$1=t.trustedTypes,e=s$1?s$1.createPolicy("lit-html",{createHTML:t=>t}):void 0,h="$lit$",o$2=`lit$${Math.random().toFixed(9).slice(2)}$`,n$1="?"+o$2,r$2=`<${n$1}>`,l=document,c=()=>l.createComment(""),a=t=>null===t||"object"!=typeof t&&"function"!=typeof t,u=Array.isArray,d=t=>u(t)||"function"==typeof t?.[Symbol.iterator],f="[ \t\n\f\r]",v=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,_=/-->/g,m=/>/g,p=RegExp(`>|${f}(?:([^\\s"'>=/]+)(${f}*=${f}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,"g"),g=/'/g,$=/"/g,y=/^(?:script|style|textarea|title)$/i,x=t=>(i,...s)=>({_$litType$:t,strings:i,values:s}),b=x(1),E=Symbol.for("lit-noChange"),A=Symbol.for("lit-nothing"),C=new WeakMap,P=l.createTreeWalker(l,129);function V(t,i){if(!u(t)||!t.hasOwnProperty("raw"))throw Error("invalid template strings array");return void 0!==e?e.createHTML(i):i}const N=(t,i)=>{const s=t.length-1,e=[];let n,l=2===i?"<svg>":3===i?"<math>":"",c=v;for(let i=0;i<s;i++){const s=t[i];let a,u,d=-1,f=0;for(;f<s.length&&(c.lastIndex=f,u=c.exec(s),null!==u);)f=c.lastIndex,c===v?"!--"===u[1]?c=_:void 0!==u[1]?c=m:void 0!==u[2]?(y.test(u[2])&&(n=RegExp("</"+u[2],"g")),c=p):void 0!==u[3]&&(c=p):c===p?">"===u[0]?(c=n??v,d=-1):void 0===u[1]?d=-2:(d=c.lastIndex-u[2].length,a=u[1],c=void 0===u[3]?p:'"'===u[3]?$:g):c===$||c===g?c=p:c===_||c===m?c=v:(c=p,n=void 0);const x=c===p&&t[i+1].startsWith("/>")?" ":"";l+=c===v?s+r$2:d>=0?(e.push(a),s.slice(0,d)+h+s.slice(d)+o$2+x):s+o$2+(-2===d?i:x);}return [V(t,l+(t[s]||"<?>")+(2===i?"</svg>":3===i?"</math>":"")),e]};class S{constructor({strings:t,_$litType$:i},e){let r;this.parts=[];let l=0,a=0;const u=t.length-1,d=this.parts,[f,v]=N(t,i);if(this.el=S.createElement(f,e),P.currentNode=this.el.content,2===i||3===i){const t=this.el.content.firstChild;t.replaceWith(...t.childNodes);}for(;null!==(r=P.nextNode())&&d.length<u;){if(1===r.nodeType){if(r.hasAttributes())for(const t of r.getAttributeNames())if(t.endsWith(h)){const i=v[a++],s=r.getAttribute(t).split(o$2),e=/([.?@])?(.*)/.exec(i);d.push({type:1,index:l,name:e[2],strings:s,ctor:"."===e[1]?I:"?"===e[1]?L:"@"===e[1]?z:H}),r.removeAttribute(t);}else t.startsWith(o$2)&&(d.push({type:6,index:l}),r.removeAttribute(t));if(y.test(r.tagName)){const t=r.textContent.split(o$2),i=t.length-1;if(i>0){r.textContent=s$1?s$1.emptyScript:"";for(let s=0;s<i;s++)r.append(t[s],c()),P.nextNode(),d.push({type:2,index:++l});r.append(t[i],c());}}}else if(8===r.nodeType)if(r.data===n$1)d.push({type:2,index:l});else {let t=-1;for(;-1!==(t=r.data.indexOf(o$2,t+1));)d.push({type:7,index:l}),t+=o$2.length-1;}l++;}}static createElement(t,i){const s=l.createElement("template");return s.innerHTML=t,s}}function M(t,i,s=t,e){if(i===E)return i;let h=void 0!==e?s._$Co?.[e]:s._$Cl;const o=a(i)?void 0:i._$litDirective$;return h?.constructor!==o&&(h?._$AO?.(false),void 0===o?h=void 0:(h=new o(t),h._$AT(t,s,e)),void 0!==e?(s._$Co??=[])[e]=h:s._$Cl=h),void 0!==h&&(i=M(t,h._$AS(t,i.values),h,e)),i}class R{constructor(t,i){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=i;}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){const{el:{content:i},parts:s}=this._$AD,e=(t?.creationScope??l).importNode(i,true);P.currentNode=e;let h=P.nextNode(),o=0,n=0,r=s[0];for(;void 0!==r;){if(o===r.index){let i;2===r.type?i=new k(h,h.nextSibling,this,t):1===r.type?i=new r.ctor(h,r.name,r.strings,this,t):6===r.type&&(i=new Z(h,this,t)),this._$AV.push(i),r=s[++n];}o!==r?.index&&(h=P.nextNode(),o++);}return P.currentNode=l,e}p(t){let i=0;for(const s of this._$AV) void 0!==s&&(void 0!==s.strings?(s._$AI(t,s,i),i+=s.strings.length-2):s._$AI(t[i])),i++;}}class k{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,i,s,e){this.type=2,this._$AH=A,this._$AN=void 0,this._$AA=t,this._$AB=i,this._$AM=s,this.options=e,this._$Cv=e?.isConnected??true;}get parentNode(){let t=this._$AA.parentNode;const i=this._$AM;return void 0!==i&&11===t?.nodeType&&(t=i.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,i=this){t=M(this,t,i),a(t)?t===A||null==t||""===t?(this._$AH!==A&&this._$AR(),this._$AH=A):t!==this._$AH&&t!==E&&this._(t):void 0!==t._$litType$?this.$(t):void 0!==t.nodeType?this.T(t):d(t)?this.k(t):this._(t);}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t));}_(t){this._$AH!==A&&a(this._$AH)?this._$AA.nextSibling.data=t:this.T(l.createTextNode(t)),this._$AH=t;}$(t){const{values:i,_$litType$:s}=t,e="number"==typeof s?this._$AC(t):(void 0===s.el&&(s.el=S.createElement(V(s.h,s.h[0]),this.options)),s);if(this._$AH?._$AD===e)this._$AH.p(i);else {const t=new R(e,this),s=t.u(this.options);t.p(i),this.T(s),this._$AH=t;}}_$AC(t){let i=C.get(t.strings);return void 0===i&&C.set(t.strings,i=new S(t)),i}k(t){u(this._$AH)||(this._$AH=[],this._$AR());const i=this._$AH;let s,e=0;for(const h of t)e===i.length?i.push(s=new k(this.O(c()),this.O(c()),this,this.options)):s=i[e],s._$AI(h),e++;e<i.length&&(this._$AR(s&&s._$AB.nextSibling,e),i.length=e);}_$AR(t=this._$AA.nextSibling,s){for(this._$AP?.(false,true,s);t!==this._$AB;){const s=i$1(t).nextSibling;i$1(t).remove(),t=s;}}setConnected(t){ void 0===this._$AM&&(this._$Cv=t,this._$AP?.(t));}}class H{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,i,s,e,h){this.type=1,this._$AH=A,this._$AN=void 0,this.element=t,this.name=i,this._$AM=e,this.options=h,s.length>2||""!==s[0]||""!==s[1]?(this._$AH=Array(s.length-1).fill(new String),this.strings=s):this._$AH=A;}_$AI(t,i=this,s,e){const h=this.strings;let o=false;if(void 0===h)t=M(this,t,i,0),o=!a(t)||t!==this._$AH&&t!==E,o&&(this._$AH=t);else {const e=t;let n,r;for(t=h[0],n=0;n<h.length-1;n++)r=M(this,e[s+n],i,n),r===E&&(r=this._$AH[n]),o||=!a(r)||r!==this._$AH[n],r===A?t=A:t!==A&&(t+=(r??"")+h[n+1]),this._$AH[n]=r;}o&&!e&&this.j(t);}j(t){t===A?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"");}}class I extends H{constructor(){super(...arguments),this.type=3;}j(t){this.element[this.name]=t===A?void 0:t;}}class L extends H{constructor(){super(...arguments),this.type=4;}j(t){this.element.toggleAttribute(this.name,!!t&&t!==A);}}class z extends H{constructor(t,i,s,e,h){super(t,i,s,e,h),this.type=5;}_$AI(t,i=this){if((t=M(this,t,i,0)??A)===E)return;const s=this._$AH,e=t===A&&s!==A||t.capture!==s.capture||t.once!==s.once||t.passive!==s.passive,h=t!==A&&(s===A||e);e&&this.element.removeEventListener(this.name,this,s),h&&this.element.addEventListener(this.name,this,t),this._$AH=t;}handleEvent(t){"function"==typeof this._$AH?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t);}}class Z{constructor(t,i,s){this.element=t,this.type=6,this._$AN=void 0,this._$AM=i,this.options=s;}get _$AU(){return this._$AM._$AU}_$AI(t){M(this,t);}}const B=t.litHtmlPolyfillSupport;B?.(S,k),(t.litHtmlVersions??=[]).push("3.3.2");const D=(t,i,s)=>{const e=s?.renderBefore??i;let h=e._$litPart$;if(void 0===h){const t=s?.renderBefore??null;e._$litPart$=h=new k(i.insertBefore(c(),t),t,void 0,s??{});}return h._$AI(t),h};

/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */const s=globalThis;class i extends y$1{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0;}createRenderRoot(){const t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){const r=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=D(r,this.renderRoot,this.renderOptions);}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(true);}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(false);}render(){return E}}i._$litElement$=true,i["finalized"]=true,s.litElementHydrateSupport?.({LitElement:i});const o$1=s.litElementPolyfillSupport;o$1?.({LitElement:i});(s.litElementVersions??=[]).push("4.2.2");

/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */const o={attribute:true,type:String,converter:u$1,reflect:false,hasChanged:f$1},r$1=(t=o,e,r)=>{const{kind:n,metadata:i}=r;let s=globalThis.litPropertyMetadata.get(i);if(void 0===s&&globalThis.litPropertyMetadata.set(i,s=new Map),"setter"===n&&((t=Object.create(t)).wrapped=true),s.set(r.name,t),"accessor"===n){const{name:o}=r;return {set(r){const n=e.get.call(this);e.set.call(this,r),this.requestUpdate(o,n,t,true,r);},init(e){return void 0!==e&&this.C(o,void 0,t,e),e}}}if("setter"===n){const{name:o}=r;return function(r){const n=this[o];e.call(this,r),this.requestUpdate(o,n,t,true,r);}}throw Error("Unsupported decorator location: "+n)};function n(t){return (e,o)=>"object"==typeof o?r$1(t,e,o):((t,e,o)=>{const r=e.hasOwnProperty(o);return e.constructor.createProperty(o,t),r?Object.getOwnPropertyDescriptor(e,o):void 0})(t,e,o)}

/**
 * @license
 * Copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */function r(r){return n({...r,state:true,attribute:false})}

const SCHEMA = [
    { name: "title", selector: { text: {} } },
    {
        name: "min_confidence",
        selector: {
            number: {
                min: 0,
                max: 1,
                step: 0.05,
                mode: "slider",
            },
        },
    },
    {
        name: "max_rows",
        selector: {
            number: {
                min: 0,
                max: 100,
                step: 1,
                mode: "box",
            },
        },
    },
    {
        name: "compact",
        selector: { boolean: {} },
    },
    {
        name: "tts_target_entity_id",
        selector: { entity: { domain: "media_player" } },
    },
    {
        name: "tts_engine_entity_id",
        selector: { entity: { domain: "tts" } },
    },
    {
        name: "search",
        selector: { text: {} },
    },
    {
        name: "include_dismissed",
        selector: { boolean: {} },
    },
    {
        name: "include_applied",
        selector: { boolean: {} },
    },
    {
        name: "sort_by",
        selector: {
            select: {
                mode: "dropdown",
                options: [
                    { value: "confidence", label: "Confidence (highest first)" },
                    { value: "age", label: "Age (newest first)" },
                    { value: "detector", label: "Detector name" },
                    { value: "area", label: "Area" },
                ],
            },
        },
    },
    {
        name: "group_by",
        selector: {
            select: {
                mode: "dropdown",
                options: [
                    { value: "none", label: "No grouping" },
                    { value: "detector", label: "By detector" },
                    { value: "area", label: "By area" },
                    { value: "floor", label: "By floor" },
                    { value: "integration", label: "By integration" },
                    { value: "label", label: "By label" },
                ],
            },
        },
    },
];
const LABELS = {
    title: "Card title",
    min_confidence: "Minimum confidence",
    max_rows: "Max rows (leave blank for auto-fit)",
    compact: "Compact tile mode (single-line summary linking to panel)",
    tts_target_entity_id: "TTS target (media_player) — shows 🔊 Read aloud",
    tts_engine_entity_id: "TTS engine (optional override)",
    search: "Default search filter (case-insensitive title match)",
    include_dismissed: "Show dismissed insights",
    include_applied: "Show insights you've already applied",
    sort_by: "Sort order",
    group_by: "Group rows by",
};
class HaInsightsCardEditor extends i {
    constructor() {
        super(...arguments);
        this._computeLabel = (schema) => LABELS[schema.name] ?? schema.name;
    }
    setConfig(config) {
        this._config = config;
    }
    render() {
        if (!this._config)
            return b ``;
        // ha-form is a custom element that HA's frontend registers globally.
        // We don't import a class; we just render the tag.
        return b `
      <ha-form
        .hass=${this.hass}
        .data=${this._config}
        .schema=${SCHEMA}
        .computeLabel=${this._computeLabel}
        @value-changed=${this._onChanged}
      ></ha-form>
    `;
    }
    _onChanged(ev) {
        const incoming = { ...ev.detail.value };
        // Strip empties so the YAML stays clean (HA's frontend inserts "" for
        // text fields the user clears, which would otherwise persist as noise).
        for (const key of Object.keys(incoming)) {
            const value = incoming[key];
            if (value === "" || value === null) {
                delete incoming[key];
            }
        }
        // type field is required by Lovelace; preserve it
        if (this._config?.type && !("type" in incoming)) {
            incoming.type = this._config.type;
        }
        const next = incoming;
        this._config = next;
        this.dispatchEvent(new CustomEvent("config-changed", {
            detail: { config: next },
            bubbles: true,
            composed: true,
        }));
    }
}
__decorate([
    n({ attribute: false })
], HaInsightsCardEditor.prototype, "hass", void 0);
__decorate([
    r()
], HaInsightsCardEditor.prototype, "_config", void 0);
// Guard against double-registration — same rationale as ha-insights-card.
if (!customElements.get("ha-insights-card-editor")) {
    customElements.define("ha-insights-card-editor", HaInsightsCardEditor);
}

class BulkAreaAssignDialog extends i {
    constructor() {
        super(...arguments);
        this.open = false;
        this._tab = "devices";
        this._areas = [];
        this._devices = [];
        this._entities = [];
        /** Map keyed by `device:ID` or `entity:ID` → chosen area_id (or ""
         *  for "clear area"). Empty means no pending change for that row. */
        this._pending = new Map();
        this._loading = false;
        this._saving = false;
        this._savedCount = 0;
        this._failedRows = [];
        // v1.2.14: structured per-row record of what got assigned so the
        // success banner can render a "Kitchen TV → Kitchen" list instead
        // of a bare count. Format: { label, area_name } per successfully-
        // saved row, in the order they were saved.
        this._savedAssignments = [];
        /** When true, includes rows that already have an area. Default off
         *  so the first-load picture is "things you haven't classified yet". */
        this._showAll = false;
        this._filter = "";
        /** v1.5.0 — Optional HA Insights enrichment. When the HA Insights
         *  integration is installed (v1.10.0+), we call
         *  `home_insights/identify_capability` to score each entity's name
         *  quality and sort worst-named entities to the top so the user
         *  tackles the genuinely-confusing ones first.
         *
         *  Falls back silently when the WS endpoint isn't available
         *  (vanilla HA install). The dialog remains fully functional
         *  without the integration — sorting just stays alphabetical.
         *
         *  Map: entity_id → { score (0-1), tier, chosen_name }.
         *  Empty map = enrichment didn't run or returned no data. */
        this._nameQuality = new Map();
        /** v1.6.0 — Per-entity identify capability (from the same
         *  home_insights/identify_capability response that populates
         *  _nameQuality). When `supported === true` we render a 🔆 button
         *  the user can click to fire `home_insights/identify_entity`. */
        this._identifyCaps = new Map();
        /** v1.6.0 — Per-entity identify-request lifecycle state.
         *
         *  - "idle": no request in flight, button is clickable
         *  - "pending": request fired, awaiting response (button disabled)
         *  - "success": last request succeeded — show ✓ confirmation
         *  - "failed": last request errored — show ✗ + error message
         *
         *  Success / failed states auto-clear after 3s so the user can
         *  click again. */
        this._identifyState = new Map();
        /** v1.7.0 — Dedup hints from HA Insights v1.10.3+. Each entity's
         *  `same_as` array enumerates other entity_ids that LOOK like the
         *  same physical device based on static identifiers (MAC, Bluetooth,
         *  Zigbee IEEE, IP, identifier overlap, mfr+model+via_device).
         *
         *  We threshold at confidence >= 0.7 for the pill — below that the
         *  signal is too noisy to surface in row context (a tooltip is one
         *  thing; suggesting "this is the same device" without strong
         *  evidence undermines trust).
         *
         *  Bidirectional: a → b match AND b → a match both surface; the
         *  user can act on either side. Don't try to deduplicate the
         *  display — both rows benefit from seeing the link. */
        this._dedupHints = new Map();
        /** v1.8.0 — Touch-test (perturbation) modal state.
         *
         *  Phase B of Find-My-Device: when the user can't fire 🔆 because
         *  the entity is a passive sensor, they click 👆 instead. Modal
         *  opens with per-device_class instruction ("place a finger on it
         *  for 10s"), user clicks Start, server captures baseline + opens
         *  N-second listening window, returns ranked z-scores. Modal
         *  shows the result — including the killer **elimination**
         *  message when the entity that spiked isn't the one the user
         *  clicked. */
        this._touchTestOpen = false;
        this._touchTestEntity = "";
        this._touchTestDeviceClass = "";
        this._touchTestGuide = null;
        this._touchTestPhase = "loading_guide";
        this._touchTestResult = null;
        this._touchTestCountdown = 0;
        this._touchTestError = "";
        this._touchTestCandidateCount = 0;
        /** Browser-side countdown timer ID, so we can cancel on close. */
        this._touchTestTimer = null;
        // v1.10.0 — BLE live-find state.
        /** Map of entity_id → BLE capability from the v1.12.0 backend.
         *  Populated alongside _identifyCaps / _dedupHints in the single
         *  WS round-trip on dialog open. */
        this._bleCaps = new Map();
        this._bleFindOpen = false;
        this._bleFindEntity = "";
        this._bleFindAddress = "";
        this._bleFindLatest = null;
        /** Per-scanner latest reading for the multi-proxy view. */
        this._blePerScanner = new Map();
        /** Recent smoothed readings for trend arrow. Cap at 8 entries
         *  (~8 seconds of context at 1Hz advertisement rate). */
        this._bleTrendBuffer = [];
        this._bleFindError = "";
        /** Returned by `subscribeMessage` — call it to unsubscribe. */
        this._bleFindUnsub = null;
        /** v1.2.7 — Structured filters in addition to free-text search.
         *  Empty string = "all". Populated from the actual data on fetch
         *  so users only see options they have. */
        this._filterIntegration = "";
        this._filterManufacturer = "";
        this._filterDomain = ""; // entities tab only
        this._onClose = () => {
            if (this._saving)
                return; // don't close mid-save
            this.open = false;
            this.dispatchEvent(new CustomEvent("closed", { bubbles: true, composed: true }));
        };
    }
    /** Fallback set used when the integration is older than v1.10.7
     *  and doesn't include `perturbable` in the identify_capability
     *  response. Keep loosely in sync with
     *  lib/perturbation_capability.py — drift here only affects
     *  pre-v1.10.7 integrations, which won't get new device_classes
     *  added to the list anyway. */
    static { this._PERTURBABLE_FALLBACK = new Set([
        "temperature",
        "humidity",
        "carbon_dioxide",
        "illuminance",
        "sound_pressure",
        "moisture",
    ]); }
    updated(changedProps) {
        // Lazy-fetch when the dialog transitions to open.
        if (changedProps.has("open") && this.open && this.hass) {
            void this._fetchRegistries();
        }
    }
    async _fetchRegistries(opts) {
        if (!this.hass)
            return;
        this._loading = true;
        this._error = undefined;
        // v1.2.14: don't reset saved-state on post-save refreshes — the
        // success banner is the user's confirmation that the save worked,
        // and clobbering it 50ms later made the dialog look like it
        // "popped up for a second then disappeared". On dialog OPEN we
        // do reset (preserveSavedState left default) since the prior
        // session's saved-state is stale by then.
        if (!opts?.preserveSavedState) {
            this._pending = new Map();
            this._savedCount = 0;
            this._failedRows = [];
            this._savedAssignments = [];
        }
        try {
            const [areas, devices, entities] = await Promise.all([
                this.hass.connection.sendMessagePromise({
                    type: "config/area_registry/list",
                }),
                this.hass.connection.sendMessagePromise({
                    type: "config/device_registry/list",
                }),
                this.hass.connection.sendMessagePromise({
                    type: "config/entity_registry/list",
                }),
            ]);
            this._areas = (areas ?? []).slice().sort((a, b) => a.name.localeCompare(b.name));
            this._devices = (devices ?? []).filter((d) => !d.disabled_by);
            this._entities = (entities ?? []).filter((e) => !e.disabled_by && !e.hidden_by);
            // v1.5.0 — opportunistic name-quality enrichment via HA
            // Insights. Fire-and-forget; the dialog renders alphabetically
            // while this is in flight, then re-sorts on completion.
            void this._fetchNameQuality();
        }
        catch (err) {
            this._error = `Could not load registries: ${this._errMsg(err)}`;
        }
        finally {
            this._loading = false;
        }
    }
    /** Best-effort fetch of name_quality scores via HA Insights
     *  v1.10.0+. Silently absent on installs without the integration. */
    async _fetchNameQuality() {
        if (!this.hass || this._entities.length === 0)
            return;
        // Only ask for entities without areas — the others won't be shown
        // by default and don't need scoring. Cap at 500 to keep the WS
        // round-trip snappy even on huge installs.
        const candidates = this._entities
            .filter((e) => !e.area_id)
            .slice(0, 500)
            .map((e) => e.entity_id);
        if (candidates.length === 0)
            return;
        try {
            const resp = await this.hass.connection.sendMessagePromise({
                type: "home_insights/identify_capability",
                entity_ids: candidates,
            });
            const nextNq = new Map();
            const nextCaps = new Map();
            const nextDedup = new Map();
            for (const [eid, cap] of Object.entries(resp.capabilities ?? {})) {
                if (cap.name_quality) {
                    nextNq.set(eid, {
                        score: cap.name_quality.score,
                        tier: cap.name_quality.tier,
                        chosen_name: cap.name_quality.chosen_name,
                    });
                }
                if (cap.method && cap.description !== undefined) {
                    nextCaps.set(eid, {
                        method: cap.method,
                        description: cap.description,
                        supported: !!cap.supported,
                        device_class: cap.device_class ?? null,
                        perturbable: cap.perturbable,
                        perturbation_state: cap.perturbation_state,
                    });
                }
                if (Array.isArray(cap.same_as) && cap.same_as.length > 0) {
                    nextDedup.set(eid, cap.same_as);
                }
            }
            this._nameQuality = nextNq;
            this._identifyCaps = nextCaps;
            this._dedupHints = nextDedup;
            // v1.10.0 — fire-and-forget BLE capability fetch in parallel.
            // Done as a separate call (different WS endpoint) so failure
            // doesn't poison the identify_capability result above.
            void this._fetchBleCapability(candidates);
        }
        catch {
            // HA Insights not installed, or older version without the
            // endpoint, or a transient error. Sorting falls back to
            // alphabetical; no UI message — this is enrichment, not a
            // hard dependency.
        }
    }
    _errMsg(err) {
        if (err instanceof Error)
            return err.message;
        if (typeof err === "string")
            return err;
        try {
            return JSON.stringify(err);
        }
        catch {
            return "unknown error";
        }
    }
    _deviceLabel(d) {
        return (d.name_by_user ||
            d.name ||
            d.id ||
            "(unnamed device)");
    }
    _entityLabel(e) {
        return e.name || e.original_name || e.entity_id;
    }
    /** v1.5.0 — render a tier indicator badge per entity row.
     *
     *  Only renders when name_quality data is available AND the tier
     *  is informative (skip the middle "friendly" tier to avoid
     *  cluttering rows that don't need user attention). Mac-pattern
     *  and generic_domain tiers get prominent icons — those are the
     *  rows the user should focus on. Cloud / user-override tiers
     *  get a subtle ✓ that says "this name is fine, no need to
     *  re-investigate."
     *
     *  Tooltip carries the score + reason from the integration so
     *  power users can verify the call.
     */
    _renderNameQualityBadge(nq) {
        if (!nq)
            return A;
        let icon = "";
        let title = "";
        const pct = Math.round(nq.score * 100);
        switch (nq.tier) {
            case "mac_pattern":
                icon = "🆔";
                title =
                    `MAC-pattern name (score ${pct}%). This entity needs ` +
                        "identification — the name doesn't tell you what it is.";
                break;
            case "generic_domain":
                icon = "❓";
                title =
                    `Generic entity_id (score ${pct}%). The name carries little ` +
                        "signal; consider identifying the device.";
                break;
            case "mfr_model":
                icon = "🏷️";
                title =
                    `Manufacturer + model (score ${pct}%). Better than a hex blob, ` +
                        "but doesn't tell you which physical device it is.";
                break;
            case "user_override":
                icon = "✏️";
                title = `User-named (score ${pct}%). No identification needed.`;
                break;
            case "cloud":
                icon = "☁️";
                title =
                    `Cloud-authoritative name (score ${pct}%). Imported from the ` +
                        "integration's app — should match what you named it there.";
                break;
            case "friendly_set":
                // Skip the badge for friendly_set — it's the common case and
                // would clutter the list. The score-based sorting still
                // ranks it above mac_pattern / generic_domain.
                return A;
            default:
                return A;
        }
        return b `<span
      class="name-quality-badge name-quality-${nq.tier}"
      role="img"
      aria-label="${title}"
      title="${title}"
      >${icon}</span
    >`;
    }
    /** v1.6.0 — render the 🔆 identify button for one entity row.
     *
     *  Only renders when the integration says the entity supports an
     *  identify signal (flash_light / strobe_light / play_chime /
     *  siren_chirp / switch_toggle). For unsupported entities (passive
     *  sensors, etc.) returns nothing — Phase B perturbation testing
     *  is the future answer there.
     *
     *  Button state is per-entity (see `_identifyState`):
     *    idle    → 🔆 clickable
     *    pending → ⏳ disabled, "calling…"
     *    success → ✓ "<description>", auto-clears after 3 s
     *    failed  → ✗ "<error>", auto-clears after 3 s
     */
    _renderIdentifyButton(entity_id) {
        const cap = this._identifyCaps.get(entity_id);
        if (!cap || !cap.supported)
            return A;
        const st = this._identifyState.get(entity_id) ?? { status: "idle" };
        let label = "🔆";
        let title = `Identify: ${cap.description}`;
        let disabled = false;
        let cls = "identify-btn identify-btn-idle";
        switch (st.status) {
            case "pending":
                label = "⏳";
                title = "Sending identify…";
                disabled = true;
                cls = "identify-btn identify-btn-pending";
                break;
            case "success":
                label = "✓";
                title = st.message ?? cap.description;
                cls = "identify-btn identify-btn-success";
                break;
            case "failed":
                label = "✗";
                title = st.message ?? "Identify failed";
                cls = "identify-btn identify-btn-failed";
                break;
        }
        return b `<button
      class="${cls}"
      ?disabled=${disabled}
      aria-label="${title}"
      title="${title}"
      @click=${(e) => {
            e.stopPropagation();
            void this._fireIdentify(entity_id);
        }}
    >
      ${label}
    </button>`;
    }
    /** v1.6.0 — call home_insights/identify_entity for one entity.
     *  Manages the per-entity lifecycle state map. */
    async _fireIdentify(entity_id) {
        if (!this.hass)
            return;
        // Don't re-fire while a request is in flight for this entity.
        const current = this._identifyState.get(entity_id);
        if (current?.status === "pending")
            return;
        this._setIdentifyState(entity_id, { status: "pending" });
        try {
            const resp = await this.hass.connection.sendMessagePromise({
                type: "home_insights/identify_entity",
                entity_id,
            });
            this._setIdentifyState(entity_id, {
                status: "success",
                message: `Done: ${resp.description} (${resp.calls_made} call${resp.calls_made === 1 ? "" : "s"})`,
            });
            // Auto-clear the success state after 3 s so the button is
            // clickable again if the user wants to try a second time
            // (e.g., they missed the flash).
            setTimeout(() => {
                const st = this._identifyState.get(entity_id);
                if (st?.status === "success") {
                    this._setIdentifyState(entity_id, { status: "idle" });
                }
            }, 3000);
        }
        catch (err) {
            this._setIdentifyState(entity_id, {
                status: "failed",
                message: this._errMsg(err),
            });
            setTimeout(() => {
                const st = this._identifyState.get(entity_id);
                if (st?.status === "failed") {
                    this._setIdentifyState(entity_id, { status: "idle" });
                }
            }, 3000);
        }
    }
    _setIdentifyState(entity_id, state) {
        const next = new Map(this._identifyState);
        next.set(entity_id, state);
        this._identifyState = next;
    }
    /** v1.7.0 — render the 🔗 dedup pill for one entity row.
     *
     *  Surfaces when HA Insights v1.10.3+ reports a high-confidence
     *  (>= 0.7) same_as candidate — i.e. another HA entity that looks
     *  like the SAME physical device via static identifiers (MAC,
     *  Bluetooth, Zigbee IEEE, IP, identifier overlap).
     *
     *  Common scenarios this catches:
     *    - Tuya plug paired via Tuya cloud AND via BLE scanner
     *    - Govee Cloud + Govee BLE
     *    - Hue Bridge + Matter bridging the same Hue light
     *    - Shelly Cloud + local API
     *
     *  When you see the pill, the assignment you make to THIS entity
     *  should probably mirror to its `same_as` peer (and vice versa).
     *  The pill's tooltip shows the matching signal so the user can
     *  judge whether the dedup call is right (MAC = trust it; mfr +
     *  model + via_device = treat as a hint, verify before acting).
     *
     *  Cap: surface only the top candidate to keep the row compact.
     *  Detail dialog (future) can show the full list.
     */
    _renderDedupPill(entity_id) {
        const hints = this._dedupHints.get(entity_id);
        if (!hints || hints.length === 0)
            return A;
        // hints are pre-sorted server-side, descending by confidence.
        const top = hints[0];
        if (top.confidence < 0.7)
            return A;
        const otherLabel = this._shortEntityLabel(top.entity_id);
        const extraCount = hints.length - 1;
        const extraSuffix = extraCount > 0 ? ` (+ ${extraCount} other)` : "";
        const confPct = Math.round(top.confidence * 100);
        const title = `Looks like the same physical device as ${top.entity_id} ` +
            `— ${top.reason}, ${confPct}% confidence` +
            `${extraSuffix}. Assignments made here probably want to ` +
            "mirror to the linked entity (and vice versa).";
        return b `<span
      class="dedup-pill"
      role="img"
      aria-label="${title}"
      title="${title}"
      >🔗 ${otherLabel}${extraSuffix}</span
    >`;
    }
    /** Short label for inline display in the dedup pill.
     *  Prefer the entity's friendly name when we have it (via the
     *  entity registry); fall back to its entity_id object_id. */
    _shortEntityLabel(entity_id) {
        const e = this._entities.find((x) => x.entity_id === entity_id);
        if (e) {
            const lbl = e.name || e.original_name;
            if (lbl)
                return lbl;
        }
        const dot = entity_id.indexOf(".");
        return dot > 0 ? entity_id.slice(dot + 1) : entity_id;
    }
    // ===== v1.8.0 — touch-test (perturbation) =====
    /** Look up an entity's device_class from its live state attributes.
     *  Returns "" when no state or no device_class attribute. */
    _deviceClassOf(entity_id) {
        const state = this.hass?.states?.[entity_id];
        if (!state)
            return "";
        const dc = state.attributes?.device_class;
        return typeof dc === "string" ? dc.toLowerCase() : "";
    }
    /** Render the 👆 touch-test button next to the entity name.
     *
     *  Only renders when:
     *    - the entity has a device_class in the perturbable set
     *    - AND the entity is NOT identify-supported (otherwise 🔆 is
     *      the better affordance — no need for an alternative)
     *
     *  This is the v1.10 Phase B affordance: passive sensors that
     *  can't self-announce get user-driven perturbation testing
     *  instead, with the killer elimination outcome.
     */
    _renderTouchTestButton(entity_id) {
        const cap = this._identifyCaps.get(entity_id);
        if (cap?.supported) {
            // Identify is a stronger signal — skip the touch-test button.
            return A;
        }
        // v1.9.0 — prefer the server's authoritative `perturbable` field
        // (integration v1.10.7+). Fallback to the local hardcoded set
        // when paired with an older integration. Final fallback to "no
        // button" if neither the server nor a local check resolves.
        const dc = cap?.device_class ?? this._deviceClassOf(entity_id);
        const isPerturbable = cap?.perturbable !== undefined
            ? cap.perturbable
            : BulkAreaAssignDialog._PERTURBABLE_FALLBACK.has(dc);
        if (!isPerturbable)
            return A;
        // Keep the dc fallback for openTouchTest below — server didn't
        // tell us, but the local set says yes, so we have *some* class
        // to work with.
        if (!dc)
            return A;
        return b `<button
      class="touch-test-btn"
      aria-label="BETA: touch test — physically perturb the sensor and see which entity spikes"
      title="BETA: Touch test. Physically perturb the sensor and HA Insights identifies which entity actually spiked. Thresholds still being calibrated."
      @click=${(e) => {
            e.stopPropagation();
            void this._openTouchTest(entity_id, dc);
        }}
    >
      👆 <span class="maturity-badge">🟡 BETA</span>
    </button>`;
    }
    /** Open the touch-test modal for the clicked entity. Fetches the
     *  per-device_class guide so we can show the instruction + window
     *  before the user commits to Start. */
    async _openTouchTest(entity_id, device_class) {
        if (!this.hass)
            return;
        this._touchTestEntity = entity_id;
        this._touchTestDeviceClass = device_class;
        this._touchTestGuide = null;
        this._touchTestResult = null;
        this._touchTestError = "";
        this._touchTestPhase = "loading_guide";
        this._touchTestCandidateCount = this._collectCandidates(device_class).length;
        this._touchTestOpen = true;
        try {
            const resp = await this.hass.connection.sendMessagePromise({
                type: "home_insights/perturbation_guide",
                device_class,
            });
            if (!resp.supported) {
                this._touchTestPhase = "error";
                this._touchTestError =
                    resp.reason ?? `device_class '${device_class}' isn't perturbable.`;
                return;
            }
            this._touchTestGuide = {
                instruction: resp.instruction ?? "",
                expected_delta: resp.expected_delta ?? 0,
                listening_window_s: resp.listening_window_s ?? 30,
                perturb_duration_s: resp.perturb_duration_s ?? 10,
            };
            this._touchTestPhase = "ready";
        }
        catch (err) {
            this._touchTestPhase = "error";
            this._touchTestError = this._errMsg(err);
        }
    }
    /** Collect all entities with the given device_class to use as
     *  candidates for the perturbation test. We test ALL of them so
     *  the elimination logic can fire — touching what the user
     *  thinks is X but a different entity spikes is THE moment. */
    _collectCandidates(device_class) {
        const out = [];
        for (const e of this._entities) {
            if (this._deviceClassOf(e.entity_id) === device_class) {
                out.push(e.entity_id);
            }
        }
        return out;
    }
    /** Fire the test. Starts a clientside countdown for UX and the
     *  WS request in parallel; they should complete at roughly the
     *  same time (server sleeps for window_s seconds). */
    async _fireTouchTest() {
        if (!this.hass || !this._touchTestGuide)
            return;
        const candidates = this._collectCandidates(this._touchTestDeviceClass);
        if (candidates.length === 0) {
            this._touchTestPhase = "error";
            this._touchTestError = `No candidates with device_class '${this._touchTestDeviceClass}'.`;
            return;
        }
        const window_s = this._touchTestGuide.listening_window_s;
        this._touchTestPhase = "running";
        this._touchTestCountdown = window_s;
        this._touchTestTimer = setInterval(() => {
            this._touchTestCountdown = Math.max(0, this._touchTestCountdown - 1);
            if (this._touchTestCountdown === 0 && this._touchTestTimer != null) {
                clearInterval(this._touchTestTimer);
                this._touchTestTimer = null;
            }
        }, 1000);
        try {
            const resp = await this.hass.connection.sendMessagePromise({
                type: "home_insights/perturbation_test",
                device_class: this._touchTestDeviceClass,
                candidate_entity_ids: candidates,
                listening_window_s: window_s,
            });
            this._touchTestResult = resp;
            this._touchTestPhase = "done";
        }
        catch (err) {
            this._touchTestPhase = "error";
            this._touchTestError = this._errMsg(err);
        }
        finally {
            if (this._touchTestTimer != null) {
                clearInterval(this._touchTestTimer);
                this._touchTestTimer = null;
            }
        }
    }
    /** Close the modal + cancel any in-flight timer. */
    _closeTouchTest() {
        if (this._touchTestTimer != null) {
            clearInterval(this._touchTestTimer);
            this._touchTestTimer = null;
        }
        this._touchTestOpen = false;
        this._touchTestResult = null;
        this._touchTestGuide = null;
        this._touchTestError = "";
    }
    /** Reset to "ready" so the user can run the test again without
     *  closing + reopening. Keeps the loaded guide. */
    _retryTouchTest() {
        this._touchTestResult = null;
        this._touchTestError = "";
        if (this._touchTestTimer != null) {
            clearInterval(this._touchTestTimer);
            this._touchTestTimer = null;
        }
        this._touchTestPhase = "ready";
    }
    // ===== v1.10.0 — BLE live-find =====
    /** Fetch BLE capability for the same entity batch the
     *  identify_capability call covered. Requires HA Insights
     *  v1.12.0+. Silent fallback when the endpoint is absent
     *  (older integration / no bluetooth integration loaded). */
    async _fetchBleCapability(entity_ids) {
        if (!this.hass || entity_ids.length === 0)
            return;
        try {
            const resp = await this.hass.connection.sendMessagePromise({
                type: "home_insights/ble_capability",
                entity_ids,
            });
            const next = new Map();
            for (const [eid, cap] of Object.entries(resp.capabilities ?? {})) {
                next.set(eid, cap);
            }
            this._bleCaps = next;
        }
        catch {
            // HA Insights pre-v1.12.0 — no BLE capability endpoint. No 📡
            // buttons rendered; user proceeds with identify/touch-test as
            // their only Find-My-Device options.
        }
    }
    /** Render the 📡 button on rows where the entity is BLE-trackable.
     *
     *  EXPERIMENTAL — brand new in v1.12.0; depends on BLE proxies or
     *  the HA companion app's BLE scanner being active. The button is
     *  rendered with a visible "EXP" tag so users understand this is
     *  not as mature as 🔆 or 👆. */
    _renderBleFindButton(entity_id) {
        const cap = this._bleCaps.get(entity_id);
        if (!cap || !cap.is_trackable)
            return A;
        return b `<button
      class="ble-find-btn"
      aria-label="${cap.reason} — Experimental: BLE live-find streams real-time RSSI"
      title="EXPERIMENTAL — BLE live-find. ${cap.reason}"
      @click=${(e) => {
            e.stopPropagation();
            this._openBleFind(entity_id);
        }}
    >
      📡 <span class="maturity-badge">🧪 EXP</span>
    </button>`;
    }
    /** Open the BLE-find modal and start the WS subscription. */
    _openBleFind(entity_id) {
        const cap = this._bleCaps.get(entity_id);
        if (!cap || !cap.bluetooth_address || !this.hass)
            return;
        this._bleFindEntity = entity_id;
        this._bleFindAddress = cap.bluetooth_address;
        this._bleFindLatest = null;
        this._blePerScanner = new Map();
        this._bleTrendBuffer = [];
        this._bleFindError = "";
        this._bleFindOpen = true;
        void this._subscribeBleFind();
    }
    async _subscribeBleFind() {
        if (!this.hass)
            return;
        if (this._bleFindUnsub != null) {
            this._bleFindUnsub();
            this._bleFindUnsub = null;
        }
        try {
            this._bleFindUnsub =
                await this.hass.connection.subscribeMessage((event) => this._handleBleEvent(event), {
                    type: "home_insights/ble_live_find",
                    bluetooth_address: this._bleFindAddress,
                });
        }
        catch (err) {
            this._bleFindError = this._errMsg(err);
        }
    }
    _handleBleEvent(event) {
        const now = Date.now();
        this._bleFindLatest = { ...event, received_at: now };
        const nextScanner = new Map(this._blePerScanner);
        nextScanner.set(event.scanner, {
            rssi_smoothed: event.rssi_smoothed,
            received_at: now,
        });
        this._blePerScanner = nextScanner;
        // Trend buffer: keep last 8 smoothed readings.
        const nextTrend = [...this._bleTrendBuffer, event.rssi_smoothed];
        if (nextTrend.length > 8)
            nextTrend.shift();
        this._bleTrendBuffer = nextTrend;
    }
    _closeBleFind() {
        if (this._bleFindUnsub != null) {
            this._bleFindUnsub();
            this._bleFindUnsub = null;
        }
        this._bleFindOpen = false;
        this._bleFindLatest = null;
        this._blePerScanner = new Map();
        this._bleTrendBuffer = [];
        this._bleFindError = "";
    }
    /** Compute the trend arrow + label from the rolling smoothed RSSI
     *  buffer. Comparing the latest 2 readings to the previous 3
     *  smooths over the per-advertisement jitter the 3s EMA hasn't
     *  killed yet. */
    _bleTrend() {
        const buf = this._bleTrendBuffer;
        if (buf.length < 4)
            return { arrow: "·", label: "settling" };
        const recent = (buf[buf.length - 1] + buf[buf.length - 2]) / 2;
        const earlier = (buf[buf.length - 4] + buf[buf.length - 3]) / 2;
        const delta = recent - earlier;
        if (delta > 2)
            return { arrow: "↑", label: "getting closer" };
        if (delta < -2)
            return { arrow: "↓", label: "getting further" };
        return { arrow: "→", label: "stable" };
    }
    /** Bucket an RSSI value into a color/temperature label. */
    _rssiBucket(rssi) {
        if (rssi >= -55)
            return { label: "HOT", cls: "rssi-hot" };
        if (rssi >= -70)
            return { label: "warm", cls: "rssi-warm" };
        if (rssi >= -85)
            return { label: "cool", cls: "rssi-cool" };
        return { label: "cold", cls: "rssi-cold" };
    }
    /** Render the BLE live-find modal. */
    _renderBleFindModal() {
        if (!this._bleFindOpen)
            return A;
        const latest = this._bleFindLatest;
        const trend = this._bleTrend();
        const bucket = latest ? this._rssiBucket(latest.rssi_smoothed) : null;
        const perScanner = Array.from(this._blePerScanner.entries())
            .map(([scanner, data]) => ({ scanner, ...data }))
            .sort((a, b) => b.rssi_smoothed - a.rssi_smoothed);
        return b `
      <div class="ble-find-backdrop" @click=${this._closeBleFind}>
        <div
          class="ble-find-modal"
          @click=${(e) => e.stopPropagation()}
        >
          <div class="ble-find-header">
            <span class="ble-find-title">
              📡 BLE Live-Find: ${this._bleFindEntity}
              <span class="maturity-badge maturity-badge-large">🧪 EXPERIMENTAL</span>
            </span>
            <button
              class="ble-find-close"
              aria-label="Close"
              @click=${this._closeBleFind}
            >
              ×
            </button>
          </div>
          <div class="ble-find-body">
            <p class="ble-find-meta">
              Address: <code>${this._bleFindAddress}</code>
            </p>
            ${this._bleFindError
            ? b `<p class="ble-find-error">⚠ ${this._bleFindError}</p>`
            : A}
            ${latest
            ? b `
                  <div class="ble-find-reading ${bucket?.cls ?? ""}">
                    <div class="ble-find-rssi">
                      ${latest.rssi_smoothed} dBm
                      <span class="ble-find-trend">${trend.arrow}</span>
                    </div>
                    <div class="ble-find-label">
                      ${bucket?.label ?? ""} · ${trend.label}
                    </div>
                  </div>
                `
            : b `
                  <p class="ble-find-waiting">
                    Listening for advertisements… make sure the HA
                    companion app's BLE scanner is enabled (Settings →
                    Companion App → Bluetooth), or that an ESPHome
                    BLE proxy is online and within range.
                  </p>
                `}
            ${perScanner.length > 1
            ? b `
                  <div class="ble-find-proxy-table">
                    <div class="ble-find-proxy-header">
                      Per-proxy RSSI (multi-proxy triangulation):
                    </div>
                    ${perScanner.map((p, i) => b `
                        <div class="ble-find-proxy-row">
                          <span class="ble-find-proxy-name">${p.scanner}</span>
                          <span class="ble-find-proxy-rssi">
                            ${p.rssi_smoothed.toFixed(1)} dBm
                          </span>
                          ${i === 0
                ? b `<span class="ble-find-proxy-tag">closest</span>`
                : A}
                        </div>
                      `)}
                  </div>
                `
            : A}
            <p class="ble-find-help">
              Walk toward where you think the device is. RSSI <b>rises</b>
              (closer to 0 dBm) as you approach. Multipath / walls /
              mirrors can cause sudden jumps — keep moving and trust the
              trend over individual readings.
            </p>
          </div>
        </div>
      </div>
    `;
    }
    /** Render the touch-test modal. Phase-driven; renders only when
     *  `_touchTestOpen` is true. */
    _renderTouchTestModal() {
        if (!this._touchTestOpen)
            return A;
        return b `
      <div
        class="touch-test-backdrop"
        @click=${this._closeTouchTest}
      >
        <div
          class="touch-test-modal"
          @click=${(e) => e.stopPropagation()}
        >
          <div class="touch-test-header">
            <span class="touch-test-title">
              👆 Touch test: ${this._touchTestEntity}
            </span>
            <button
              class="touch-test-close"
              aria-label="Close"
              @click=${this._closeTouchTest}
            >
              ×
            </button>
          </div>
          <div class="touch-test-body">
            ${this._renderTouchTestPhase()}
          </div>
        </div>
      </div>
    `;
    }
    /** Per-phase body content. Switches on _touchTestPhase. */
    _renderTouchTestPhase() {
        switch (this._touchTestPhase) {
            case "loading_guide":
                return b `<p>Loading instructions…</p>`;
            case "error":
                return b `
          <p class="touch-test-error">
            ⚠ ${this._touchTestError}
          </p>
          <div class="touch-test-actions">
            <button @click=${this._closeTouchTest}>Close</button>
          </div>
        `;
            case "ready": {
                const guide = this._touchTestGuide;
                return b `
          <p>${guide.instruction}</p>
          <p class="touch-test-meta">
            Listening window: <b>${guide.listening_window_s}s</b> ·
            ${this._touchTestCandidateCount}
            ${this._touchTestDeviceClass}
            ${this._touchTestCandidateCount === 1 ? "sensor" : "sensors"}
            will be monitored.
          </p>
          <div class="touch-test-actions">
            <button class="primary" @click=${() => this._fireTouchTest()}>
              Start touch test
            </button>
            <button @click=${this._closeTouchTest}>Cancel</button>
          </div>
        `;
            }
            case "running": {
                const guide = this._touchTestGuide;
                const elapsed = guide.listening_window_s - this._touchTestCountdown;
                const pct = Math.min(100, Math.round((elapsed / guide.listening_window_s) * 100));
                return b `
          <p class="touch-test-prompt">
            🟢 <b>Touch the sensor now!</b>
          </p>
          <div class="touch-test-progress">
            <div
              class="touch-test-progress-fill"
              style="width: ${pct}%;"
            ></div>
          </div>
          <p class="touch-test-meta">
            ${this._touchTestCountdown}s remaining ·
            watching ${this._touchTestCandidateCount}
            ${this._touchTestDeviceClass}
            ${this._touchTestCandidateCount === 1 ? "sensor" : "sensors"}…
          </p>
        `;
            }
            case "done":
                return this._renderTouchTestResult();
        }
        return A;
    }
    /** Render the final result, with phase-aware copy for the
     *  elimination case (top_match != clicked entity). */
    _renderTouchTestResult() {
        const result = this._touchTestResult;
        if (!result)
            return A;
        const clicked = this._touchTestEntity;
        if (result.decision === "no_signal") {
            return b `
        <p class="touch-test-no-signal">
          ❌ No clear spike detected.
        </p>
        <p class="touch-test-meta">${result.reason}</p>
        <div class="touch-test-actions">
          <button class="primary" @click=${() => this._retryTouchTest()}>
            Try again
          </button>
          <button @click=${this._closeTouchTest}>Close</button>
        </div>
      `;
        }
        if (result.decision === "ambiguous") {
            const spiked = result.candidates.filter((c) => c.spike_detected);
            return b `
        <p class="touch-test-ambiguous">
          ⚠ Multiple candidates spiked together.
        </p>
        <ul class="touch-test-candidate-list">
          ${spiked.map((c) => b `
              <li>
                <b>${c.entity_id}</b>
                — z=${c.z_score.toFixed(1)},
                Δ=${c.peak_delta.toFixed(2)}
              </li>
            `)}
        </ul>
        <p class="touch-test-meta">${result.reason}</p>
        <div class="touch-test-actions">
          <button class="primary" @click=${() => this._retryTouchTest()}>
            Try again
          </button>
          <button @click=${this._closeTouchTest}>Close</button>
        </div>
      `;
        }
        // decision === "clear"
        const top = result.candidates[0];
        if (result.top_match !== clicked) {
            // THE elimination moment.
            return b `
        <p class="touch-test-elimination">
          ⚠ Mislabel detected!
        </p>
        <p class="touch-test-elim-detail">
          You touched what was labelled <b>${clicked}</b>, but
          <b>${result.top_match}</b> actually spiked
          (z=${top.z_score.toFixed(1)},
          Δ=${top.peak_delta.toFixed(2)}).
        </p>
        <p class="touch-test-meta">
          These two entities are probably mislabeled — the physical
          sensor you touched is reported as
          <b>${result.top_match}</b>, not ${clicked}. Check the
          device names in HA and rename accordingly.
        </p>
        <div class="touch-test-actions">
          <button class="primary" @click=${() => this._retryTouchTest()}>
            Try again
          </button>
          <button @click=${this._closeTouchTest}>Close</button>
        </div>
      `;
        }
        // Clear match AND the user clicked the right entity.
        const unit = this._unitFor(result.top_match);
        return b `
      <p class="touch-test-success">
        ✓ Clear match: <b>${result.top_match}</b>
      </p>
      <p class="touch-test-meta">
        Spiked Δ=${top.peak_delta.toFixed(2)}${unit ? " " + unit : ""}
        (z=${top.z_score.toFixed(1)}). ${result.reason}
      </p>
      <div class="touch-test-actions">
        <button class="primary" @click=${() => this._retryTouchTest()}>
          Run again
        </button>
        <button @click=${this._closeTouchTest}>Close</button>
      </div>
    `;
    }
    /** v1.9.0 — pull unit_of_measurement off the entity's live state.
     *  Returns "" when the entity has no state or no unit attribute.
     *  Reactive: if the user reconfigures the unit, the next render
     *  picks it up. */
    _unitFor(entity_id) {
        const state = this.hass?.states?.[entity_id];
        if (!state)
            return "";
        const u = state.attributes?.unit_of_measurement;
        return typeof u === "string" ? u : "";
    }
    _areaNameById(area_id) {
        if (!area_id)
            return "";
        return this._areas.find((a) => a.area_id === area_id)?.name ?? area_id;
    }
    /** v1.2.7 — Available filter values, derived from the loaded data
     *  so users only see options that exist in their install.
     *  Sorted alphabetically. Empty strings filtered out. */
    _availableIntegrations() {
        const set = new Set();
        if (this._tab === "devices") {
            for (const d of this._devices) {
                d.config_entries?.[0];
                // Manufacturer is a more reliable signal at device level.
            }
        }
        else {
            for (const e of this._entities) {
                if (e.platform)
                    set.add(e.platform);
            }
        }
        return [...set].sort();
    }
    _availableManufacturers() {
        const set = new Set();
        for (const d of this._devices) {
            if (d.manufacturer)
                set.add(d.manufacturer);
        }
        return [...set].sort();
    }
    _availableDomains() {
        const set = new Set();
        for (const e of this._entities) {
            const dot = e.entity_id.indexOf(".");
            if (dot > 0)
                set.add(e.entity_id.slice(0, dot));
        }
        return [...set].sort();
    }
    _filteredDevices() {
        const f = this._filter.trim().toLowerCase();
        const fMfr = this._filterManufacturer;
        return this._devices.filter((d) => {
            if (!this._showAll && d.area_id)
                return false;
            if (fMfr && d.manufacturer !== fMfr)
                return false;
            if (!f)
                return true;
            const hay = (this._deviceLabel(d) + " " + (d.manufacturer ?? "") + " " +
                (d.model ?? "")).toLowerCase();
            return hay.includes(f);
        });
    }
    _filteredEntities() {
        const f = this._filter.trim().toLowerCase();
        const fInt = this._filterIntegration;
        const fDom = this._filterDomain;
        const filtered = this._entities.filter((e) => {
            // Skip entities whose device already has an area (cascade
            // handles them). User can flip Show All to override.
            if (!this._showAll) {
                if (e.area_id)
                    return false;
                if (e.device_id) {
                    const dev = this._devices.find((d) => d.id === e.device_id);
                    if (dev?.area_id)
                        return false;
                }
            }
            if (fInt && e.platform !== fInt)
                return false;
            if (fDom) {
                const dot = e.entity_id.indexOf(".");
                const dom = dot > 0 ? e.entity_id.slice(0, dot) : "";
                if (dom !== fDom)
                    return false;
            }
            if (!f)
                return true;
            return e.entity_id.toLowerCase().includes(f) ||
                this._entityLabel(e).toLowerCase().includes(f);
        });
        // v1.5.0 — when HA Insights name_quality data is available,
        // sort worst-named entities to the top so the user attacks the
        // genuinely-confusing ones (BLE MACs, hex blobs) first. Entities
        // missing a score (no enrichment or not in the batch) sort to
        // the end so the high-quality entities don't crowd them out.
        // Stable secondary sort by entity_id keeps the order deterministic.
        if (this._nameQuality.size > 0) {
            filtered.sort((a, b) => {
                const sa = this._nameQuality.get(a.entity_id)?.score ?? 1.5;
                const sb = this._nameQuality.get(b.entity_id)?.score ?? 1.5;
                if (sa !== sb)
                    return sa - sb;
                return a.entity_id.localeCompare(b.entity_id);
            });
        }
        return filtered;
    }
    _onPick(key, area_id) {
        const next = new Map(this._pending);
        if (area_id === "__unchanged__") {
            next.delete(key);
        }
        else {
            next.set(key, area_id);
        }
        this._pending = next;
    }
    async _save() {
        if (!this.hass || this._pending.size === 0)
            return;
        this._saving = true;
        this._failedRows = [];
        this._savedCount = 0;
        this._savedAssignments = [];
        const failed = [];
        const succeededKeys = [];
        const summary = [];
        for (const [key, area_id] of this._pending.entries()) {
            const [kind, id] = key.split(":", 2);
            // v1.2.14: capture the human-readable label + area name BEFORE
            // the registry update succeeds, so the post-save summary can
            // show "Kitchen TV → Kitchen" rather than just an ID.
            const label = this._labelForKey(kind, id);
            const areaName = area_id
                ? this._areaNameById(area_id)
                : "(no area)";
            try {
                if (kind === "device") {
                    await this.hass.connection.sendMessagePromise({
                        type: "config/device_registry/update",
                        device_id: id,
                        area_id: area_id || null,
                    });
                }
                else if (kind === "entity") {
                    await this.hass.connection.sendMessagePromise({
                        type: "config/entity_registry/update_entity",
                        entity_id: id,
                        area_id: area_id || null,
                    });
                }
                succeededKeys.push(key);
                summary.push({ label, area_name: areaName });
            }
            catch (err) {
                failed.push(`${label}: ${this._errMsg(err)}`);
            }
        }
        // v1.2.14: drop successfully-saved rows from _pending so the
        // "Save N changes" button reflects only the work still owed.
        // Pre-v1.2.14 the pending map was never cleared, so the button
        // re-armed itself forever and a second click would attempt to
        // re-save rows the registry already accepted.
        if (succeededKeys.length > 0) {
            const next = new Map(this._pending);
            for (const k of succeededKeys)
                next.delete(k);
            this._pending = next;
        }
        this._savedCount = summary.length;
        this._savedAssignments = summary;
        this._failedRows = failed;
        this._saving = false;
        // Refresh registries so the table reflects the saved state.
        // preserveSavedState=true keeps the success banner visible —
        // pre-v1.2.14 we wiped _savedCount inside _fetchRegistries, which
        // made the success banner flash and disappear immediately.
        await this._fetchRegistries({ preserveSavedState: true });
        // Emit so the host can refresh its own list / fire a scan.
        this.dispatchEvent(new CustomEvent("assignments-saved", {
            detail: { saved: summary.length, failed: failed.length },
            bubbles: true,
            composed: true,
        }));
    }
    /** v1.2.14: friendly label for a pending row key, used in the
     *  post-save summary. Devices fall back to `<no name>` if HA gave
     *  us a device with neither name nor name_by_user. */
    _labelForKey(kind, id) {
        if (kind === "device") {
            const d = this._devices.find((x) => x.id === id);
            return (d?.name_by_user || d?.name || `<device ${id.slice(0, 8)}…>`);
        }
        if (kind === "entity") {
            const e = this._entities.find((x) => x.entity_id === id);
            return e?.name || id;
        }
        return id;
    }
    _renderAreaPicker(key, currentAreaId) {
        const pendingValue = this._pending.get(key);
        // Three-state value: "__unchanged__" (initial), area_id (picked),
        // or "" (explicit clear). Default selected = pendingValue ?? current.
        const selected = pendingValue !== undefined
            ? pendingValue
            : (currentAreaId ?? "__unchanged__");
        return b `
      <select
        class="area-picker"
        .value=${selected}
        @change=${(e) => {
            const v = e.target.value;
            this._onPick(key, v);
        }}
        ?disabled=${this._saving}
      >
        <option value="__unchanged__">
          ${currentAreaId
            ? `keep current (${this._areaNameById(currentAreaId)})`
            : "Pick area…"}
        </option>
        ${currentAreaId
            ? b `<option value="">— clear area —</option>`
            : A}
        ${this._areas.map((a) => b `<option value=${a.area_id}>${a.name}</option>`)}
      </select>
    `;
    }
    _renderDeviceRows() {
        const rows = this._filteredDevices();
        if (rows.length === 0) {
            return b `<div class="empty">
        ${this._showAll
                ? "No devices match the current filter."
                : "Every device has an Area assigned. Toggle Show all to reassign."}
      </div>`;
        }
        return b `
      <table>
        <colgroup>
          <col class="col-name" />
          <col class="col-meta" />
          <col class="col-current" />
          <col class="col-new" />
        </colgroup>
        <thead>
          <tr>
            <th>Device</th>
            <th>Manufacturer / Model</th>
            <th>Current area</th>
            <th>New area</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((d) => b `
              <tr>
                <td class="name">${this._deviceLabel(d)}</td>
                <td class="meta">
                  ${d.manufacturer ?? ""}${d.model ? ` · ${d.model}` : ""}
                </td>
                <td class="current">
                  ${d.area_id
            ? this._areaNameById(d.area_id)
            : b `<em>none</em>`}
                </td>
                <td>${this._renderAreaPicker(`device:${d.id}`, d.area_id)}</td>
              </tr>
            `)}
        </tbody>
      </table>
    `;
    }
    _renderEntityRows() {
        const rows = this._filteredEntities();
        if (rows.length === 0) {
            return b `<div class="empty">
        ${this._showAll
                ? "No entities match the current filter."
                : "Every entity has an Area (directly or via its device). Toggle Show all to reassign."}
      </div>`;
        }
        return b `
      <table>
        <colgroup>
          <col class="col-name" />
          <col class="col-meta" />
          <col class="col-current" />
          <col class="col-new" />
        </colgroup>
        <thead>
          <tr>
            <th>Entity</th>
            <th>Device</th>
            <th>Current area</th>
            <th>New area</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((e) => {
            const dev = e.device_id
                ? this._devices.find((d) => d.id === e.device_id)
                : undefined;
            const effectiveArea = e.area_id ?? dev?.area_id ?? null;
            const nq = this._nameQuality.get(e.entity_id);
            return b `
              <tr>
                <td class="name">
                  <div>
                    ${this._renderNameQualityBadge(nq)}${this._entityLabel(e)}
                    ${this._renderIdentifyButton(e.entity_id)}
                    ${this._renderTouchTestButton(e.entity_id)}
                    ${this._renderBleFindButton(e.entity_id)}
                    ${this._renderDedupPill(e.entity_id)}
                  </div>
                  <div class="meta">${e.entity_id}</div>
                </td>
                <td class="meta">${dev ? this._deviceLabel(dev) : "—"}</td>
                <td class="current">
                  ${effectiveArea
                ? b `${this._areaNameById(effectiveArea)}
                        ${dev?.area_id && !e.area_id
                    ? b `<span class="cascade">(from device)</span>`
                    : A}`
                : b `<em>none</em>`}
                </td>
                <td>
                  ${this._renderAreaPicker(`entity:${e.entity_id}`, e.area_id)}
                </td>
              </tr>
            `;
        })}
        </tbody>
      </table>
    `;
    }
    render() {
        if (!this.open)
            return A;
        const pendingCount = this._pending.size;
        return b `
      <div class="backdrop" @click=${this._onClose}>
        <div class="dialog" @click=${(e) => e.stopPropagation()}>
          <div class="header">
            <div class="title">📍 Bulk assign areas</div>
            <button class="close" aria-label="Close" @click=${this._onClose}>
              ×
            </button>
          </div>
          <div class="body">
            ${this._error
            ? b `<div class="error">${this._error}</div>`
            : A}
            ${this._savedCount > 0
            ? b `<div class="success">
                  <div class="success-headline">
                    ✓ Saved ${this._savedCount} assignment${this._savedCount === 1 ? "" : "s"}.
                  </div>
                  ${this._savedAssignments.length > 0
                ? b `<ul class="success-summary">
                        ${this._savedAssignments.map((a) => b `<li>
                            <span class="sa-label">${a.label}</span>
                            <span class="sa-arrow">→</span>
                            <span class="sa-area">${a.area_name}</span>
                          </li>`)}
                      </ul>`
                : A}
                </div>`
            : A}
            ${this._failedRows.length > 0
            ? b `<div class="error">
                  ${this._failedRows.length} row${this._failedRows.length === 1 ? "" : "s"} failed to save:
                  <ul>
                    ${this._failedRows.map((r) => b `<li>${r}</li>`)}
                  </ul>
                </div>`
            : A}
            <div class="toolbar">
              <div class="tabs">
                <button
                  class="tab ${this._tab === "devices" ? "active" : ""}"
                  @click=${() => (this._tab = "devices")}
                >
                  Devices
                </button>
                <button
                  class="tab ${this._tab === "entities" ? "active" : ""}"
                  @click=${() => (this._tab = "entities")}
                >
                  Entities
                </button>
              </div>
              <div class="filters">
                <input
                  type="search"
                  placeholder="Filter by name…"
                  .value=${this._filter}
                  @input=${(e) => (this._filter = e.target.value)}
                />
                ${this._tab === "devices"
            ? b `
                      <select
                        class="filter-select"
                        .value=${this._filterManufacturer}
                        @change=${(e) => (this._filterManufacturer = e.target.value)}
                      >
                        <option value="">All manufacturers</option>
                        ${this._availableManufacturers().map((m) => b `<option value=${m}>${m}</option>`)}
                      </select>
                    `
            : b `
                      <select
                        class="filter-select"
                        .value=${this._filterIntegration}
                        @change=${(e) => (this._filterIntegration = e.target.value)}
                      >
                        <option value="">All integrations</option>
                        ${this._availableIntegrations().map((i) => b `<option value=${i}>${i}</option>`)}
                      </select>
                      <select
                        class="filter-select"
                        .value=${this._filterDomain}
                        @change=${(e) => (this._filterDomain = e.target.value)}
                      >
                        <option value="">All types</option>
                        ${this._availableDomains().map((d) => b `<option value=${d}>${d}</option>`)}
                      </select>
                    `}
                <label class="show-all">
                  <input
                    type="checkbox"
                    .checked=${this._showAll}
                    @change=${(e) => (this._showAll = e.target.checked)}
                  />
                  Show all (incl. already assigned)
                </label>
              </div>
            </div>
            ${this._loading
            ? b `<div class="empty">Loading registries…</div>`
            : this._tab === "devices"
                ? this._renderDeviceRows()
                : this._renderEntityRows()}
            <div class="hint">
              Need a new area first?
              <a href="/config/areas/dashboard">Create one in
                Settings → Areas</a>, then re-open this dialog.
            </div>
          </div>
          <div class="footer">
            <button
              class="btn"
              @click=${this._onClose}
              ?disabled=${this._saving}
            >
              ${pendingCount > 0 ? "Cancel" : "Close"}
            </button>
            <button
              class="btn primary"
              @click=${this._save}
              ?disabled=${pendingCount === 0 || this._saving}
            >
              ${this._saving
            ? "Saving…"
            : pendingCount > 0
                ? `Save ${pendingCount} change${pendingCount === 1 ? "" : "s"}`
                : "No changes"}
            </button>
          </div>
        </div>
      </div>
      ${this._renderTouchTestModal()}
      ${this._renderBleFindModal()}
    `;
    }
    static { this.styles = i$3 `
    :host {
      /* All styling via HA CSS variables — keeps this component
         portable to HA core's frontend. */
      --bulk-row-bg: var(--card-background-color, #fff);
      --bulk-row-alt: var(--secondary-background-color, #f7f7f7);
    }
    .backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.55);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 9999;
    }
    .dialog {
      width: min(960px, 96vw);
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color, #212121);
      border-radius: 8px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
      overflow: hidden;
    }
    .header {
      padding: 14px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid var(--divider-color, #e0e0e0);
    }
    .title {
      font-size: 1.15em;
      font-weight: 500;
    }
    .close {
      background: none;
      border: none;
      font-size: 1.6em;
      cursor: pointer;
      color: var(--secondary-text-color);
    }
    .body {
      flex: 1;
      overflow: auto;
      padding: 14px 18px;
    }
    .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
      flex-wrap: wrap;
    }
    .tabs {
      display: flex;
      gap: 6px;
    }
    .tab {
      background: transparent;
      border: 1px solid var(--divider-color, #e0e0e0);
      padding: 6px 12px;
      border-radius: 16px;
      cursor: pointer;
      font-size: 0.95em;
      color: var(--secondary-text-color);
    }
    .tab.active {
      background: var(--primary-color, #4c6ef5);
      color: var(--text-primary-color, #fff);
      border-color: var(--primary-color, #4c6ef5);
    }
    .filters {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .filters input[type="search"] {
      padding: 6px 10px;
      border-radius: 4px;
      border: 1px solid var(--divider-color, #e0e0e0);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      min-width: 180px;
    }
    .filter-select {
      padding: 6px 10px;
      border-radius: 4px;
      border: 1px solid var(--divider-color, #e0e0e0);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      min-width: 130px;
    }
    .show-all {
      font-size: 0.9em;
      color: var(--secondary-text-color);
      cursor: pointer;
      user-select: none;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92em;
      table-layout: fixed;
    }
    /* v1.2.14: explicit column widths so the "New area" picker has
       room for "Pick area…" + the longest area name without truncating
       to "pick an are". Manufacturer column wraps text rather than
       eating the picker's column. */
    .col-name { width: 26%; }
    .col-meta { width: 30%; }
    .col-current { width: 14%; }
    .col-new { width: 30%; }
    td.meta {
      overflow: hidden;
      text-overflow: ellipsis;
    }
    th {
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid var(--divider-color, #e0e0e0);
      font-weight: 500;
      color: var(--secondary-text-color);
    }
    td {
      padding: 8px 10px;
      border-bottom: 1px solid var(--divider-color, #f0f0f0);
      vertical-align: top;
    }
    tbody tr:nth-child(even) {
      background: var(--bulk-row-alt);
    }
    td.name {
      font-weight: 500;
    }
    td.meta,
    div.meta {
      color: var(--secondary-text-color);
      font-size: 0.9em;
    }
    td.current em {
      color: var(--secondary-text-color);
      font-style: italic;
    }
    .cascade {
      font-size: 0.85em;
      color: var(--secondary-text-color);
      margin-left: 4px;
    }
    /* v1.5.0 — name_quality tier badge. Sits inline before the entity
     * label; tooltip carries score + reason. Low-quality tiers
     * (mac_pattern / generic_domain) get visual weight; high-quality
     * tiers (cloud / user_override) are subtle so they don't clutter. */
    .name-quality-badge {
      display: inline-block;
      margin-right: 6px;
      font-size: 0.95em;
      vertical-align: middle;
      cursor: help;
    }
    .name-quality-mac_pattern,
    .name-quality-generic_domain {
      filter: none;
      opacity: 1;
    }
    .name-quality-user_override,
    .name-quality-cloud,
    .name-quality-mfr_model {
      opacity: 0.55;
    }
    /* v1.6.0 — identify button. Small inline button; per-state color
     * swap gives clear feedback without claiming a row. */
    .identify-btn {
      margin-left: 8px;
      padding: 1px 6px;
      border: 1px solid var(--divider-color, #e0e0e0);
      border-radius: 4px;
      background: var(--card-background-color, transparent);
      cursor: pointer;
      font-size: 0.9em;
      line-height: 1.4;
      vertical-align: middle;
    }
    .identify-btn:disabled {
      cursor: progress;
    }
    .identify-btn-idle:hover {
      background: var(--primary-color, #03a9f4);
      color: var(--text-primary-color, white);
      border-color: var(--primary-color, #03a9f4);
    }
    .identify-btn-success {
      background: var(--success-color, #4caf50);
      color: var(--text-primary-color, white);
      border-color: var(--success-color, #4caf50);
    }
    .identify-btn-failed {
      background: var(--error-color, #f44336);
      color: var(--text-primary-color, white);
      border-color: var(--error-color, #f44336);
    }
    .identify-btn-pending {
      opacity: 0.7;
    }
    /* v1.7.0 — dedup pill. Inline next to the entity label; tooltip
     * explains the matching signal and which entity it links to.
     * Visually quiet (no fill, no border accent) to avoid competing
     * with the name_quality badges and the identify button — this is
     * a HINT, not a primary action. */
    .dedup-pill {
      display: inline-block;
      margin-left: 8px;
      padding: 1px 8px;
      border-radius: 10px;
      background: var(--secondary-background-color, #f5f5f5);
      color: var(--secondary-text-color);
      font-size: 0.85em;
      vertical-align: middle;
      cursor: help;
    }
    /* v1.8.0 — touch-test (perturbation) button + modal. */
    .touch-test-btn {
      margin-left: 8px;
      padding: 1px 6px;
      border: 1px solid var(--divider-color, #e0e0e0);
      border-radius: 4px;
      background: var(--card-background-color, transparent);
      cursor: pointer;
      font-size: 0.9em;
      line-height: 1.4;
      vertical-align: middle;
    }
    .touch-test-btn:hover {
      background: var(--accent-color, #ff9800);
      color: var(--text-primary-color, white);
      border-color: var(--accent-color, #ff9800);
    }
    .touch-test-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.5);
      display: flex;
      align-items: center;
      justify-content: center;
      /* v1.9.0 — parent .backdrop is z-index 9999; touch-test modal
       * must stack above it or it renders BEHIND and is unclickable. */
      z-index: 10000;
    }
    .touch-test-modal {
      background: var(--card-background-color, white);
      color: var(--primary-text-color);
      border-radius: 8px;
      min-width: 420px;
      max-width: 520px;
      padding: 0;
      box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
    }
    .touch-test-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 18px;
      border-bottom: 1px solid var(--divider-color, #e0e0e0);
    }
    .touch-test-title {
      font-weight: 600;
    }
    .touch-test-close {
      background: transparent;
      border: none;
      font-size: 1.4em;
      cursor: pointer;
      color: var(--secondary-text-color);
      line-height: 1;
    }
    .touch-test-body {
      padding: 18px;
    }
    .touch-test-body p {
      margin: 8px 0;
      line-height: 1.5;
    }
    .touch-test-meta {
      color: var(--secondary-text-color);
      font-size: 0.9em;
    }
    .touch-test-actions {
      display: flex;
      gap: 8px;
      justify-content: flex-end;
      margin-top: 16px;
    }
    .touch-test-actions button {
      padding: 6px 14px;
      border-radius: 4px;
      border: 1px solid var(--divider-color, #e0e0e0);
      background: var(--card-background-color, white);
      color: var(--primary-text-color);
      cursor: pointer;
    }
    .touch-test-actions button.primary {
      background: var(--primary-color, #03a9f4);
      color: var(--text-primary-color, white);
      border-color: var(--primary-color, #03a9f4);
    }
    .touch-test-prompt {
      font-size: 1.1em;
      text-align: center;
    }
    .touch-test-progress {
      height: 8px;
      background: var(--secondary-background-color, #f5f5f5);
      border-radius: 4px;
      overflow: hidden;
      margin: 12px 0;
    }
    .touch-test-progress-fill {
      height: 100%;
      background: var(--primary-color, #03a9f4);
      transition: width 1s linear;
    }
    .touch-test-error {
      color: var(--error-color, #f44336);
    }
    .touch-test-success {
      color: var(--success-color, #4caf50);
      font-size: 1.1em;
    }
    .touch-test-no-signal {
      font-size: 1.05em;
    }
    .touch-test-ambiguous {
      color: var(--warning-color, #ff9800);
      font-size: 1.05em;
    }
    .touch-test-elimination {
      color: var(--warning-color, #ff9800);
      font-size: 1.2em;
      font-weight: 600;
    }
    .touch-test-elim-detail {
      font-size: 1.05em;
    }
    .touch-test-candidate-list {
      list-style: none;
      padding: 0;
      margin: 8px 0;
    }
    .touch-test-candidate-list li {
      padding: 4px 0;
      border-bottom: 1px solid var(--divider-color, #e0e0e0);
    }
    /* v1.10.0 — BLE live-find button + modal + EXPERIMENTAL tags.
     * Visual heavier on the experimental cue than 🔆 / 👆 because
     * this is the newest and least field-tested affordance. */
    .ble-find-btn {
      margin-left: 8px;
      padding: 1px 8px;
      border: 1px solid var(--divider-color, #e0e0e0);
      border-radius: 4px;
      background: var(--card-background-color, transparent);
      cursor: pointer;
      font-size: 0.9em;
      line-height: 1.4;
      vertical-align: middle;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .ble-find-btn:hover {
      background: var(--primary-color, #03a9f4);
      color: var(--text-primary-color, white);
      border-color: var(--primary-color, #03a9f4);
    }
    /* Inline maturity badge — matches the existing 🟡 BETA /
     * 🧪 EXPERIMENTAL convention used by the insight-feed pills
     * (see ha-insights-card.ts _renderMaturityPill). One visual
     * language for maturity across the whole UI. The emoji
     * distinguishes BETA vs EXP; both render in muted yellow so
     * they cluster as "not yet stable" rather than two unrelated
     * categories. */
    .maturity-badge {
      display: inline-block;
      font-size: 0.7em;
      font-weight: 600;
      padding: 0 4px;
      border-radius: 3px;
      background: var(--warning-color, #ff9800);
      color: var(--text-primary-color, white);
      vertical-align: middle;
      letter-spacing: 0.3px;
    }
    .maturity-badge-large {
      font-size: 0.75em;
      padding: 2px 8px;
      border-radius: 10px;
      margin-left: 8px;
      letter-spacing: 1px;
    }
    /* EXPERIMENTAL pill in the modal header — wider, more visible */
    .exp-pill {
      display: inline-block;
      margin-left: 8px;
      font-size: 0.7em;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 10px;
      background: var(--warning-color, #ff9800);
      color: var(--text-primary-color, white);
      letter-spacing: 1px;
      vertical-align: middle;
    }
    .ble-find-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.5);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 10000;
    }
    .ble-find-modal {
      background: var(--card-background-color, white);
      color: var(--primary-text-color);
      border-radius: 8px;
      min-width: 480px;
      max-width: 600px;
      padding: 0;
      box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
    }
    .ble-find-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 18px;
      border-bottom: 1px solid var(--divider-color, #e0e0e0);
    }
    .ble-find-title {
      font-weight: 600;
    }
    .ble-find-close {
      background: transparent;
      border: none;
      font-size: 1.4em;
      cursor: pointer;
      color: var(--secondary-text-color);
      line-height: 1;
    }
    .ble-find-body {
      padding: 18px;
    }
    .ble-find-meta {
      color: var(--secondary-text-color);
      font-size: 0.9em;
    }
    .ble-find-meta code {
      background: var(--secondary-background-color, #f5f5f5);
      padding: 1px 6px;
      border-radius: 3px;
      font-family: monospace;
    }
    .ble-find-error {
      color: var(--error-color, #f44336);
    }
    .ble-find-waiting {
      color: var(--secondary-text-color);
      font-style: italic;
      padding: 12px 0;
    }
    .ble-find-reading {
      text-align: center;
      padding: 24px;
      border-radius: 8px;
      margin: 12px 0;
      transition: background 0.3s ease;
    }
    .ble-find-rssi {
      font-size: 2.4em;
      font-weight: 700;
      font-family: monospace;
    }
    .ble-find-trend {
      margin-left: 12px;
      font-size: 0.85em;
    }
    .ble-find-label {
      font-size: 1em;
      margin-top: 4px;
      opacity: 0.85;
    }
    /* RSSI temperature buckets. Closer to 0 dBm = closer device. */
    .rssi-hot {
      background: rgba(76, 175, 80, 0.25);
      color: var(--success-color, #2e7d32);
    }
    .rssi-warm {
      background: rgba(255, 193, 7, 0.2);
      color: #f57c00;
    }
    .rssi-cool {
      background: rgba(255, 152, 0, 0.15);
      color: #e65100;
    }
    .rssi-cold {
      background: rgba(244, 67, 54, 0.15);
      color: var(--error-color, #c62828);
    }
    .ble-find-proxy-table {
      margin: 12px 0;
      border: 1px solid var(--divider-color, #e0e0e0);
      border-radius: 4px;
    }
    .ble-find-proxy-header {
      padding: 8px 12px;
      background: var(--secondary-background-color, #f5f5f5);
      font-weight: 600;
      font-size: 0.9em;
    }
    .ble-find-proxy-row {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 6px 12px;
      border-top: 1px solid var(--divider-color, #e0e0e0);
    }
    .ble-find-proxy-name {
      flex: 1;
      font-family: monospace;
    }
    .ble-find-proxy-rssi {
      font-family: monospace;
    }
    .ble-find-proxy-tag {
      font-size: 0.75em;
      padding: 1px 6px;
      border-radius: 3px;
      background: var(--success-color, #4caf50);
      color: var(--text-primary-color, white);
    }
    .ble-find-help {
      color: var(--secondary-text-color);
      font-size: 0.9em;
      margin-top: 12px;
    }
    .area-picker {
      width: 100%;
      padding: 5px 8px;
      border-radius: 4px;
      border: 1px solid var(--divider-color, #e0e0e0);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
    }
    .empty {
      padding: 32px 12px;
      text-align: center;
      color: var(--secondary-text-color);
      font-style: italic;
    }
    .hint {
      margin-top: 16px;
      padding: 10px 12px;
      background: var(--secondary-background-color, #f5f5f5);
      border-radius: 4px;
      font-size: 0.88em;
      color: var(--secondary-text-color);
    }
    .hint a {
      color: var(--primary-color, #4c6ef5);
    }
    .error {
      margin-bottom: 12px;
      padding: 10px 12px;
      background: rgba(244, 67, 54, 0.08);
      border-left: 3px solid var(--error-color, #c62828);
      border-radius: 4px;
      color: var(--primary-text-color);
      font-size: 0.92em;
    }
    .success-headline {
      font-weight: 500;
    }
    .success-summary {
      margin: 8px 0 0 0;
      padding: 0;
      list-style: none;
      max-height: 200px;
      overflow-y: auto;
      font-size: 0.88em;
    }
    .success-summary li {
      display: flex;
      gap: 8px;
      padding: 4px 0;
      border-top: 1px solid rgba(76, 175, 80, 0.15);
    }
    .success-summary li:first-child {
      border-top: none;
      margin-top: 4px;
    }
    .sa-label {
      font-weight: 500;
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .sa-arrow {
      color: var(--secondary-text-color);
    }
    .sa-area {
      flex: 1;
      color: var(--success-color, #2e7d32);
    }
    .success {
      margin-bottom: 12px;
      padding: 10px 12px;
      background: rgba(76, 175, 80, 0.12);
      border-left: 3px solid var(--success-color, #4caf50);
      border-radius: 4px;
      color: var(--primary-text-color);
      font-size: 0.92em;
    }
    .footer {
      padding: 12px 18px;
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      border-top: 1px solid var(--divider-color, #e0e0e0);
      background: var(--secondary-background-color, #fafafa);
    }
    .btn {
      padding: 8px 16px;
      border-radius: 4px;
      border: 1px solid var(--divider-color, #e0e0e0);
      background: var(--card-background-color, #fff);
      color: var(--primary-text-color);
      cursor: pointer;
      font-size: 0.95em;
    }
    .btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .btn.primary {
      background: var(--primary-color, #4c6ef5);
      color: var(--text-primary-color, #fff);
      border-color: var(--primary-color, #4c6ef5);
    }
  `; }
}
__decorate([
    n({ attribute: false })
], BulkAreaAssignDialog.prototype, "hass", void 0);
__decorate([
    n({ type: Boolean, reflect: true })
], BulkAreaAssignDialog.prototype, "open", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_tab", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_areas", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_devices", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_entities", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_pending", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_loading", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_saving", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_error", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_savedCount", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_failedRows", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_savedAssignments", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_showAll", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_filter", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_nameQuality", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_identifyCaps", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_identifyState", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_dedupHints", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_touchTestOpen", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_touchTestEntity", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_touchTestDeviceClass", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_touchTestGuide", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_touchTestPhase", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_touchTestResult", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_touchTestCountdown", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_touchTestError", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_touchTestCandidateCount", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_bleCaps", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_bleFindOpen", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_bleFindEntity", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_bleFindAddress", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_bleFindLatest", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_blePerScanner", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_bleTrendBuffer", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_bleFindError", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_filterIntegration", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_filterManufacturer", void 0);
__decorate([
    r()
], BulkAreaAssignDialog.prototype, "_filterDomain", void 0);
// v1.2.24: switched from `@customElement` decorator to guarded
// `customElements.define` to match the other three top-level elements
// in this bundle. The decorator throws on re-registration via the
// scoped-custom-element-registry polyfill, and HA re-mounts the panel
// on tab-return — the throw at module-eval time killed all subsequent
// code on the page, leaving the panel blank until a hard refresh.
// Wrapping in `customElements.get(...) ?? define(...)` makes the
// second module evaluation a no-op.
if (!customElements.get("bulk-area-assign-dialog")) {
    customElements.define("bulk-area-assign-dialog", BulkAreaAssignDialog);
}

const CARD_PROTOCOL_VERSION = 1;
const DEFAULT_MAX_ROWS = 8;
class HaInsightsCard extends i {
    constructor() {
        super(...arguments);
        this._config = { type: "custom:ha-insights-card" };
        this._insights = [];
        // v1.2.9: `_loading` removed. It was a lifecycle flag that could
        // get stuck (WS hang, missed update, etc.) and produced a blank
        // "Loading…" curtain — the worst kind of UX failure (you don't
        // know if it's broken or just slow). The card now renders based
        // on the data it actually has: insights, _hello (server contact),
        // _error (visible failure). Empty data + no error = empty state
        // with a "Run scan now" CTA, not a stuck curtain. Mirrors how
        // every native HA panel handles this — they never show "Loading…"
        // as a terminal state, only as a transient indicator at most.
        // True while a scan is in flight — render method shows a "Scanning…"
        // curtain instead of the live-mutating insight list. Cleared by the
        // ha-insights-refresh handler (which also fetches the canonical
        // post-scan view).
        this._scanInProgress = false;
        this._explainBusy = false;
        // Per-insight busy flag for the audit_suggest LLM call. Distinct
        // from Refine so an in-flight suggest on one row doesn't disable
        // refine on another.
        this._auditSuggestBusy = null;
        // v1.2.27 Suggested-Additions state. `_suggestAddBusy` tracks the insight_id
        // whose candidate fetch is in flight (drives the pill's loading state).
        // `_suggestAddDialog` holds the modal's working set when open: the
        // candidate list as returned by the backend, the user's checkbox
        // selection, and the apply-in-flight flag. Closing the modal resets it
        // to undefined; the next open is a fresh fetch.
        this._suggestAddBusy = null;
        this._suggestAddDialog = undefined;
        this._ttsBusy = false;
        // v1.2.28: History view toggle. When true, ws_list is called with
        // include_retired/include_dismissed/include_snoozed=true so the
        // user can see and (un-)retire their prior lifecycle decisions.
        // Default OFF — day-to-day view stays clean.
        this._showHistory = false;
        this._refineBusy = false;
        /** v0.9 phase 6: ephemeral hypothesis text per anomaly id. Not persisted. */
        this._hypothesisById = new Map();
        this._hypothesizeBusy = false;
        /** v1.0 RC #2: per-insight Conversation API thread id, so consecutive
         * Refines on the same insight maintain agent context. Cleared on
         * Apply / Keep Original / explicit "Reset conversation". */
        this._refineConversationById = new Map();
        /** v1.0 RC #2: per-insight Refine turn counter for UI display. */
        this._refineTurnsById = new Map();
        this._testBusy = false;
        this._scanBusy = false;
        /** Per-insight refined preview held in card state until Apply or Keep Original. */
        this._refinedById = new Map();
        /** Per-insight alias/description rename edits, applied as payload_override on Apply. */
        this._renameEdits = new Map();
        /** Per-insight in-progress follow-up feedback for the next Refine call. */
        this._feedbackById = new Map();
        /** Per-insight free-form JSON edits to the payload (v0.8 phase 3). */
        this._payloadEditsById = new Map();
        /** Set of insight ids currently in edit mode. */
        this._editingPayloadFor = new Set();
        /** Per-insight parse error from the last Apply attempt (e.g. "Invalid JSON"). */
        this._payloadParseErrorById = new Map();
        /** Per-insight redaction preview state — shown when user clicks "What gets sent?" */
        this._previewById = new Map();
        this._previewBusy = false;
        /** v1.10.4: in-flight flag for the 🔆 Identify-this-entity button in
         *  the detail-dialog. Used to disable the button while the WS round-
         *  trip is in progress. Single boolean (not per-insight) because only
         *  one identify can fire at a time per dialog.
         *
         *  v1.10.7 — superseded by the looping modal below. Kept here so any
         *  legacy callers don't error. */
        this._identifyBusy = false;
        /** v1.10.7: looping-identify modal state. Pre-v1.10.7 the Identify
         *  button fired once and showed a toast — many devices flash too
         *  quickly to find, and the toast disappeared while users were
         *  still searching. v1.10.7 wraps the action in a modal that fires
         *  the identifier every IDENTIFY_INTERVAL_MS until the user clicks
         *  "Found it!" or "Stop". */
        this._identifyOpen = false;
        this._identifyEntityId = "";
        this._identifyMethod = "";
        this._identifyCount = 0;
        this._identifyError = "";
        /** v1.10.7: Set of entity_ids currently being identified. Cohort or
         *  multi-entity insights (lagged_correlation pairs,
         *  physical_device_link pairs, cohort_members lists) surface every
         *  referenced entity as a checkbox in the modal — user toggles them
         *  off as they find each physical device. The recurring timer fires
         *  identify on every entity still in this set. */
        this._identifySelected = new Set();
        this._identifyAllEntities = [];
        this._identifyTimer = null;
        /** v1.10.9: default to firing ONE entity at a time. User can opt
         *  into "Fire all simultaneously" via a toggle in the modal — but
         *  the default mental model matches "I'm looking for ONE thing"
         *  and avoids strobing a whole cohort of lights at once (especially
         *  bad with Circadian Lighting + auto-off automations). */
        this._identifyOneAtATime = true;
        /** v1.10.9: state snapshot per entity captured at first fire so we
         *  can restore at Stop / Found / uncheck. Maps entity_id → the
         *  state value + relevant attributes (brightness/color_temp/rgb)
         *  read from `hass.states` BEFORE identify started.
         *
         *  Without this, FALLBACK strobe mode (cheap Tuya/Zigbee lights that
         *  don't expose SUPPORT_FLASH) leaves the light ON at default
         *  brightness/color, which Circadian then re-overrides 1-2s later
         *  AND tripping any auto-off automation tied to the state change.
         *  Restoration honors whatever the user / Circadian / scenes had
         *  set the entity to before they hit Identify. */
        this._identifySnapshots = new Map();
        /** v1.10.6: BLE live-find state. Populated when user clicks the
         *  📡 BLE find button in the insight detail-dialog. Subscription
         *  delivers per-scanner RSSI updates; modal shows latest reading +
         *  trend arrow so the user can wave their phone around and watch the
         *  signal get stronger/weaker. */
        this._bleFindOpen = false;
        this._bleFindEntity = "";
        this._bleFindAddress = "";
        this._bleFindLatest = null;
        this._bleTrendBuffer = [];
        this._bleFindError = "";
        this._bleFindUnsub = null;
        /** v1.1 Refine-existing-automation modal state. Separate from the
         *  per-insight dialog because we're not in an insight context here —
         *  user clicked the ✏️ icon on a 🔁/🤖 pill. Carries the loaded
         *  automation, the in-progress feedback, and the refined diff after
         *  the LLM round-trip. Set undefined while closed. */
        /** v1.1: insight ids whose cohort_members list is currently shown
         *  expanded. Click "▸ show N" to toggle. Per-row state; not persisted. */
        this._expandedCohorts = new Set();
        /** v1.2.6 — Open flag for the standalone <bulk-area-assign-dialog>
         *  component. State lives INSIDE the dialog (so it's portable to HA
         *  core); the card just toggles the open flag. */
        this._bulkAreaAssignOpen = false;
        /**
         * v0.5: rows that fit in the card's currently-rendered height. Updated
         * by ResizeObserver. Used as the row cap when the user hasn't set
         * max_rows explicitly. -1 means "not yet measured; use the default."
         */
        this._autoMaxRows = -1;
        // Populated by _filtered() — the total count BEFORE the max_rows
        // cap is applied. Used by _renderCompactTile so the dashboard tile
        // reports the true number of insights even when the cap clips the
        // rendered list to e.g. 1 row.
        this._totalFilteredCount = 0;
        // v1.2.13: re-entry guard for `_wire()`. Both connectedCallback (the
        // re-mount recovery added in v1.2.13) and `updated(changedProps)` can
        // race to fire `_wire()` within the same microtask if Lit reassigns
        // hass during element re-attachment. Without a guard we'd open two
        // subscriptions, leak the first `_unsub`, and double-handle events.
        this._wiring = false;
        // v1.2.22: post-purge suppression. Set by `ha-insights-purged` window
        // event. While Date.now() < this value, "added" subscribe events are
        // ignored so the user sees a true empty state. The integration's
        // periodic scan continues running in the background — when the
        // suppression window expires, any insights detected since then will
        // flow in normally on the next event.
        this._suppressAddedUntil = 0;
        this._keydownHandler = (e) => {
            if (e.key === "Escape" && this._dialogId) {
                this._closeDialog();
            }
        };
        this._scanStarted = () => {
            this._scanInProgress = true;
        };
        /** v1.2.22 — hard-clear insights on panel-driven purge AND set a
         *  short suppression window so post-purge "added" subscribe events
         *  (from a scan that runs before the user has time to look) are
         *  ignored. Without this, users click Purge and immediately watch
         *  insights re-flood from the next periodic scan — looks like the
         *  button doesn't work. */
        this._handlePurgedEvent = (e) => {
            const detail = e.detail;
            const ms = typeof detail?.suppressionMs === "number" ? detail.suppressionMs : 30_000;
            this._insights = [];
            this._suppressAddedUntil = Date.now() + ms;
            if (this._dialogId)
                this._closeDialog();
        };
        this._refreshFromEvent = async () => {
            // v1.2.9: no more _loading flag to manage. Render is data-driven
            // (insights / _hello / _error); this method just updates the
            // underlying data, render handles the rest. `_scanInProgress`
            // stays because it's a legitimate transient indicator a scan is
            // running RIGHT NOW (user clicked Run scan, results coming).
            if (!this.hass) {
                this._scanInProgress = false;
                return;
            }
            // Refresh hello in parallel so the footer + protocol-skew banner
            // reflect the latest deploy. Non-fatal — list-refresh is the
            // user-visible bit.
            try {
                this._hello = await this._withTimeout(this.hass.connection.sendMessagePromise({
                    type: "home_insights/hello",
                    card_version: "0.8.2",
                }), "home_insights/hello");
            }
            catch (err) {
                console.debug("ha-insights-card hello refresh failed", err);
            }
            // List is the load-bearing call. If it fails AND we have no
            // existing insights to fall back to, surface the error so the
            // user knows the card is alive and explains itself. If we DO
            // have prior insights, keep them visible — stale is better than
            // blank.
            try {
                const result = await this._withTimeout(this.hass.connection.sendMessagePromise({
                    type: "home_insights/list",
                    include_applied: Boolean(this._config.include_applied),
                    include_retired: this._showHistory,
                    include_dismissed: this._showHistory,
                    include_snoozed: this._showHistory,
                }), "home_insights/list");
                this._insights = result.insights ?? [];
                this._error = undefined;
            }
            catch (err) {
                console.warn("ha-insights-card refresh-from-event failed", err);
                if (this._insights.length === 0) {
                    this._error = `Could not refresh insights: ${this._asMessage(err)}`;
                }
            }
            finally {
                this._scanInProgress = false;
            }
        };
    }
    // v1.2.9: `_wired` removed. Used to gate the initial fetch, but
    // it was also a "we've talked to HA" signal we tracked manually —
    // which can drift from reality (subscription died but flag still
    // says wired). Replaced by checking `this._hello` directly: the
    // hello-response object IS the signal that we successfully talked
    // to the integration. If hello is undefined, we haven't fetched
    // yet; if it's set, we have. Single source of truth, can't drift.
    //
    // `_resumeCleanups` + `_installResumeHandlers` removed. HA's
    // home-assistant-js-websocket auto-reconnects on WS drop and
    // auto-resubscribes subscribeMessage handles. The visibility-
    // change handler we added in v1.2.2 was working around a problem
    // that only appeared because our `_loading` flag could stick —
    // with `_loading` gone, there's no stuck state to recover from.
    // Subscription events flow back in naturally on WS resume.
    static { this.styles = i$3 `
    :host {
      display: block;
    }
    ha-card {
      padding: 0;
      overflow: hidden;
    }
    .header {
      padding: 12px 16px 8px;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      display: flex;
      align-items: flex-start;
      gap: 12px;
    }
    .header .titles {
      flex: 1;
      min-width: 0;
    }
    .title {
      font-size: 1.2em;
      font-weight: 600;
      letter-spacing: -0.01em;
    }
    .subtitle {
      font-size: 0.8em;
      color: var(--secondary-text-color);
      margin-top: 2px;
    }
    .header a.view-all {
      flex-shrink: 0;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 0.85em;
      font-weight: 500;
      color: var(--primary-color);
      text-decoration: none;
      padding: 6px 12px;
      border-radius: 16px;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.18));
      min-height: 24px;
      transition: background 120ms, border-color 120ms;
    }
    .header a.view-all:hover {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
      border-color: var(--primary-color);
    }
    .header a.view-all ha-icon {
      --mdc-icon-size: 16px;
      width: 16px;
      height: 16px;
    }
    /* v1.2.28 — History toggle button. Same chrome as view-all so the
       two sit together cleanly in the header. Active state uses the
       warning color so the user sees "you're looking at history" at a
       glance. */
    .header .history-toggle {
      flex-shrink: 0;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 0.85em;
      font-weight: 500;
      background: transparent;
      color: var(--primary-color);
      padding: 6px 12px;
      border-radius: 16px;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.18));
      min-height: 24px;
      cursor: pointer;
      transition: background 120ms, border-color 120ms;
    }
    .header .history-toggle:hover {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
      border-color: var(--primary-color);
    }
    .header .history-toggle.history-toggle-on {
      background: var(--warning-color, #f9a825);
      color: rgba(0, 0, 0, 0.78);
      border-color: var(--warning-color, #f9a825);
    }
    /* v1.2.28 — Retire action button. Same chrome as other .action
       buttons but a muted border treatment so it reads "permanent /
       advanced" relative to Dismiss / Snooze. Not destructive enough
       to warrant a red color (it's reversible via the history view). */
    button.action.retire {
      border-style: dashed;
    }
    button.action.retire:hover:not(:disabled) {
      border-style: solid;
      border-color: var(--warning-color, #f9a825);
    }
    /* v1.2.3 — "Showing N of M — +X more →" footer for capped tiles */
    .truncation-footer {
      display: block;
      padding: 8px 16px;
      text-align: center;
      font-size: 0.85em;
      color: var(--primary-color);
      text-decoration: none;
      border-top: 1px solid var(--divider-color, #e0e0e0);
      transition: background 120ms;
    }
    .truncation-footer:hover {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
    }
    /* Compact tile: single row, full-width clickable */
    .compact-tile {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 18px 20px;
      cursor: pointer;
      transition: background 120ms;
      text-decoration: none;
      color: inherit;
    }
    .compact-tile:hover {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.03));
    }
    .compact-tile .count {
      font-size: 1.4em;
      font-weight: 500;
    }
    .compact-tile .label {
      color: var(--secondary-text-color);
      font-size: 0.85em;
      margin-top: 2px;
    }
    .compact-tile .arrow {
      font-size: 1.2em;
      color: var(--primary-color);
    }
    .skew-banner {
      background: var(--warning-color, #ff9800);
      color: white;
      padding: 8px 16px;
      font-size: 0.85em;
    }
    .empty,
    .error {
      padding: 24px 16px;
      text-align: center;
      color: var(--secondary-text-color);
    }
    .empty-actions {
      margin-top: 12px;
      display: flex;
      gap: 8px;
      justify-content: center;
      flex-wrap: wrap;
    }
    .empty-scanning {
      padding: 56px 16px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 12px;
    }
    .empty-scanning .empty-sub {
      color: var(--secondary-text-color);
      font-size: 0.85em;
    }
    .spinner {
      width: 32px;
      height: 32px;
      border: 3px solid var(--divider-color, rgba(0, 0, 0, 0.18));
      border-top-color: var(--primary-color);
      border-radius: 50%;
      animation: ha-insights-spin 0.8s linear infinite;
    }
    @keyframes ha-insights-spin {
      to {
        transform: rotate(360deg);
      }
    }
    .empty-actions a,
    .empty-actions button {
      background: none;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.18));
      color: var(--primary-text-color);
      padding: 6px 14px;
      border-radius: 6px;
      cursor: pointer;
      font: inherit;
      font-size: 0.9em;
      text-decoration: none;
    }
    .empty-actions a:hover,
    .empty-actions button:hover:not(:disabled) {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
    }
    .empty-actions button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .error {
      color: var(--error-color, #f44336);
    }
    .toast {
      background: var(--success-color, #4caf50);
      color: white;
      padding: 8px 16px;
      font-size: 0.85em;
    }
    .error-banner {
      background: var(--error-color, #f44336);
      color: white;
      padding: 10px 16px;
      font-size: 0.85em;
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }
    .error-banner button {
      background: rgba(255, 255, 255, 0.18);
      border: 1px solid rgba(255, 255, 255, 0.3);
      color: white;
      padding: 4px 10px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 0.85em;
      flex-shrink: 0;
    }
    .error-banner button:hover {
      background: rgba(255, 255, 255, 0.28);
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 8px;
      border-radius: 10px;
      font-size: 0.75em;
      font-weight: 500;
      vertical-align: middle;
    }
    .badge-off {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.08));
      color: var(--secondary-text-color);
    }
    .badge-local {
      background: rgba(76, 175, 80, 0.18);
      color: var(--success-color, #2e7d32);
    }
    .badge-cloud {
      background: rgba(255, 152, 0, 0.18);
      color: var(--warning-color, #e65100);
    }
    /* Group section header (v0.7) */
    .group-header {
      padding: 10px 16px 4px;
      font-size: 0.78em;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--secondary-text-color);
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.02));
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.06));
    }
    .row {
      padding: 12px 16px;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
      cursor: pointer;
      display: flex;
      flex-direction: column;
      gap: 6px;
      transition: background 120ms;
    }
    .row:last-child {
      border-bottom: none;
    }
    .row {
      position: relative;
    }
    .row:hover {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.05));
    }
    .row:hover::before {
      content: "";
      position: absolute;
      left: 0;
      top: 6px;
      bottom: 6px;
      width: 2px;
      background: var(--primary-color);
      border-radius: 1px;
    }
    .row-title {
      font-weight: 500;
    }
    .row-meta {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      font-size: 0.8em;
      color: var(--secondary-text-color);
    }
    /* v1.2.25: tiered meta — primary pills carry actionable state
       (confidence, applied, conflict, maturity, device-managed); secondary
       text carries identity context (detector, area, integration, age). */
    .row-meta-primary {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      font-size: 0.8em;
      color: var(--secondary-text-color);
    }
    .row-meta-secondary {
      font-size: 0.78em;
      color: var(--secondary-text-color);
      opacity: 0.85;
      line-height: 1.4;
    }
    .row-meta-secondary .sep {
      margin: 0 6px;
      opacity: 0.4;
    }
    .pill {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
      padding: 2px 8px;
      border-radius: 10px;
    }
    /* v1.1: pill + ✏️ Refine action button cluster — keeps the pill
       and its sibling button visually adjacent without disturbing
       the row's existing pill flow. */
    .automation-pill-group {
      display: inline-flex;
      align-items: center;
      gap: 2px;
    }
    .pill-action {
      background: transparent;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      padding: 1px 6px;
      border-radius: 10px;
      cursor: pointer;
      font-size: 0.95em;
      color: var(--secondary-text-color);
    }
    .coupling-badge {
      cursor: help;
      background: var(--info-color, #4a90e2);
      color: var(--text-primary-color, #fff);
      border-color: var(--info-color, #4a90e2);
      opacity: 0.85;
    }
    .coupling-badge:hover {
      opacity: 1.0;
    }
    /* v1.12.11: "newly added" badge. Sky-blue background to read as
       informational, not warning — the entity isn't broken, just new. */
    .entity-age-badge {
      cursor: help;
      background: var(--info-color, #4a90e2);
      color: var(--text-primary-color, #fff);
      border-color: var(--info-color, #4a90e2);
      opacity: 0.80;
    }
    .entity-age-badge:hover {
      opacity: 1.0;
    }
    .pill-action:hover {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.06));
    }
    /* Multi-link pill expander. <details> handles open/close; we only
       need to suppress the default disclosure triangle (Firefox) and
       style the popout list. */
    .automation-pill-details {
      display: inline-block;
      vertical-align: middle;
    }
    .automation-pill-details > summary {
      display: inline-block;
    }
    .automation-pill-details > summary::-webkit-details-marker {
      display: none;
    }
    .automation-pill-menu {
      display: flex;
      flex-direction: column;
      gap: 4px;
      margin-top: 6px;
      padding: 8px 10px;
      background: var(--card-background-color, white);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      border-radius: 8px;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
      min-width: 220px;
      max-width: 380px;
    }
    .automation-pill-row {
      display: flex;
      align-items: center;
      gap: 6px;
      justify-content: space-between;
    }
    .automation-pill-link {
      color: var(--primary-color);
      text-decoration: none;
      font-size: 0.9em;
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .automation-pill-link:hover {
      text-decoration: underline;
    }
    /* v1.1 audit findings — collapsible per-observation list shown
       under audit-row titles. Indented + secondary background so it
       reads as supporting detail, not another row. */
    .audit-findings {
      margin: 6px 0 8px 14px;
      padding: 8px 12px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.03));
      border-left: 3px solid var(--primary-color);
      border-radius: 0 6px 6px 0;
      font-size: 0.9em;
    }
    .audit-findings ul {
      margin: 0;
      padding-left: 18px;
    }
    .audit-findings li {
      margin: 2px 0;
    }
    .audit-findings .audit-fixes {
      margin-top: 6px;
      padding-top: 6px;
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
      color: var(--success-color, #2e7d32);
    }
    .audit-findings .audit-fixes strong {
      display: block;
      margin-bottom: 2px;
    }
    /* v1.1: cohort expansion — list of merged entity_ids */
    .cohort-members {
      margin-top: 6px;
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
    .cohort-member-chip {
      font-family: var(--code-font-family, monospace);
      font-size: 0.8em;
      padding: 2px 8px;
      border-radius: 4px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
      color: var(--secondary-text-color);
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .cohort-member-id {
      /* The entity_id keeps the monospace look from the parent */
    }
    .cohort-member-badge {
      font-family: var(--primary-font-family, sans-serif);
      font-size: 0.85em;
      padding: 1px 6px;
      border-radius: 10px;
    }
    .cohort-member-int {
      background: rgba(76, 110, 245, 0.15);
      color: var(--secondary-text-color);
    }
    .cohort-member-ext {
      background: rgba(255, 152, 0, 0.18);
      color: var(--warning-color, #e65100);
    }
    /* Confidence pill color coding (v0.7) */
    .pill.confidence-high {
      background: rgba(76, 175, 80, 0.18);
      color: var(--success-color, #2e7d32);
    }
    .pill.confidence-medium {
      background: rgba(255, 152, 0, 0.18);
      color: var(--warning-color, #e65100);
    }
    .pill.confidence-low {
      background: rgba(244, 67, 54, 0.15);
      color: var(--error-color, #c62828);
    }
    button.action {
      background: none;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.18));
      padding: 6px 12px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.85em;
      color: var(--primary-text-color);
    }
    button.action:hover:not(:disabled) {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
    }
    button.action:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    /* v0.8 phase 5: pulse animation on LLM-busy buttons so the user
       knows the round-trip is in flight (5-15s typical). Replaces the
       static "asking LLM…" text without changing the button copy. */
    @keyframes ha-insights-pulse {
      0%   { opacity: 0.55; }
      50%  { opacity: 1; }
      100% { opacity: 0.55; }
    }
    button.action.busy-pulse:disabled {
      opacity: 1;
      animation: ha-insights-pulse 1.4s ease-in-out infinite;
    }
    button.primary {
      background: var(--primary-color);
      color: var(--text-primary-color, white);
      border-color: var(--primary-color);
    }
    button.primary:hover:not(:disabled) {
      background: var(--dark-primary-color, var(--primary-color));
    }

    /* Modal dialog */
    .dialog-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.5);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1000;
      padding: 16px;
    }
    .dialog {
      background: var(--card-background-color, white);
      color: var(--primary-text-color);
      border-radius: 12px;
      width: 92vw;
      max-width: 900px;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
    }
    /* v1.10.7: looping-identify modal */
    .identify-dialog { max-width: 520px; }
    .identify-status {
      text-align: center;
      padding: 16px 0;
    }
    .identify-counter {
      font-size: 1.6em;
      font-weight: 600;
      color: var(--primary-text-color);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    .identify-method {
      font-size: 0.85em;
      color: var(--secondary-text-color);
      margin-top: 4px;
    }
    .identify-error {
      background: rgba(239, 108, 0, 0.1);
      color: var(--warning-color, #ef6c00);
      padding: 8px 10px;
      border-radius: 4px;
      margin-top: 8px;
      font-size: 0.85em;
      white-space: pre-wrap;
      text-align: left;
    }
    .identify-hint {
      font-size: 0.9em;
      color: var(--secondary-text-color);
      margin: 8px 0 12px 0;
    }
    .identify-entity-list {
      max-height: 240px;
      overflow-y: auto;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
      border-radius: 6px;
      padding: 6px;
    }
    .identify-entity-row {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 8px;
      cursor: pointer;
      border-radius: 4px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.9em;
    }
    .identify-entity-row:hover {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
    }
    /* v1.10.9: visual emphasis for the entity currently being identified */
    .identify-entity-row.active {
      background: rgba(245, 158, 11, 0.18);
      border-left: 3px solid var(--warning-color, #f59e0b);
    }
    .identify-mode-toggle {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      margin: 4px 0 8px 0;
      font-size: 0.85em;
      color: var(--secondary-text-color);
      cursor: pointer;
    }
    /* v1.10.6: BLE find modal — narrow + tall, centered RSSI readout */
    .ble-find-dialog { max-width: 480px; }
    .ble-rssi-block {
      text-align: center;
      padding: 24px 0;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    .ble-rssi-num { font-size: 3em; font-weight: 600; line-height: 1; }
    .ble-rssi-label {
      font-size: 1.1em;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      margin-top: 4px;
    }
    .ble-trend {
      margin-top: 12px;
      font-size: 1.4em;
      color: var(--primary-text-color);
    }
    .ble-scanner {
      margin-top: 6px;
      font-size: 0.85em;
      color: var(--secondary-text-color);
    }
    .ble-hint {
      font-size: 0.9em;
      color: var(--secondary-text-color);
      margin-top: 16px;
    }
    .ble-error {
      background: rgba(239, 68, 68, 0.1);
      color: var(--error-color, #ef4444);
      padding: 10px 12px;
      border-radius: 6px;
      margin-bottom: 12px;
      font-size: 0.9em;
    }
    /* Wide variant for the diff modal — YAML needs horizontal room */
    .dialog.dialog-wide {
      max-width: min(1400px, 96vw);
    }
    /* Phone-size — modal eats the screen, and the diff panes stack
       vertically instead of splitting side-by-side */
    @media (max-width: 720px) {
      .dialog-backdrop {
        padding: 0;
      }
      .dialog,
      .dialog.dialog-wide {
        width: 100vw;
        max-width: 100vw;
        height: 100vh;
        max-height: 100vh;
        border-radius: 0;
      }
      .diff-grid {
        grid-template-columns: 1fr !important;
      }
      .diff-grid > .diff-pane {
        max-height: 45vh;
      }
      .diff-header {
        grid-template-columns: 1fr !important;
        gap: 4px !important;
      }
    }
    .dialog-header {
      padding: 16px 20px;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }
    .dialog-title {
      font-size: 1.05em;
      font-weight: 500;
      line-height: 1.4;
    }
    .dialog-close {
      background: none;
      border: none;
      font-size: 1.6em;
      line-height: 1;
      cursor: pointer;
      color: var(--secondary-text-color);
      padding: 0 4px;
      flex-shrink: 0;
    }
    .dialog-close:hover {
      color: var(--primary-text-color);
    }
    .dialog-body {
      padding: 16px 20px;
      overflow-y: auto;
      flex: 1;
    }
    .dialog-body h4 {
      margin: 16px 0 8px;
      font-size: 0.9em;
    }
    .dialog-body h4:first-child {
      margin-top: 0;
    }
    .dialog-body pre {
      background: var(--code-background-color, rgba(0, 0, 0, 0.04));
      padding: 12px;
      border-radius: 6px;
      overflow-x: auto;
      overflow-y: auto;
      max-height: 360px;
      font-size: 0.85em;
      line-height: 1.5;
      margin: 0;
      white-space: pre;
    }
    /* v1.2.27 — Suggested-Additions modal */
    .suggest-add-intro {
      font-size: 0.92em;
      color: var(--secondary-text-color);
      margin-bottom: 14px;
      line-height: 1.5;
    }
    .suggest-add-error {
      background: var(--error-color, #db4437);
      color: var(--text-primary-color, white);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 0.9em;
      margin-bottom: 12px;
    }
    .suggest-add-empty {
      padding: 24px 12px;
      text-align: center;
      color: var(--secondary-text-color);
      font-style: italic;
    }
    .suggest-add-group {
      margin-bottom: 18px;
    }
    .suggest-add-group-header {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 6px;
      flex-wrap: wrap;
    }
    .suggest-add-group-blurb {
      font-size: 0.82em;
      color: var(--secondary-text-color);
    }
    .suggest-add-tier-chip {
      display: inline-block;
      padding: 2px 10px;
      border-radius: 12px;
      font-size: 0.74em;
      font-weight: 600;
      letter-spacing: 0.04em;
      color: white;
    }
    .suggest-add-tier-high {
      background: var(--success-color, #2e7d32);
    }
    .suggest-add-tier-medium {
      background: var(--warning-color, #f9a825);
      color: rgba(0, 0, 0, 0.78);
    }
    .suggest-add-tier-low {
      background: var(--secondary-text-color, #777);
    }
    .suggest-add-row {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 8px 10px;
      border-radius: 6px;
      cursor: pointer;
      transition: background 120ms ease;
    }
    .suggest-add-row:hover {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.03));
    }
    .suggest-add-row input[type="checkbox"] {
      margin-top: 3px;
      flex-shrink: 0;
    }
    .suggest-add-row-text {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }
    .suggest-add-eid {
      font-family: var(--code-font-family, monospace);
      font-size: 0.9em;
      word-break: break-all;
    }
    .suggest-add-reasons {
      font-size: 0.78em;
      color: var(--secondary-text-color);
      line-height: 1.4;
    }
    .suggest-add-footer {
      padding: 12px 20px;
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .suggest-add-count {
      font-size: 0.88em;
      color: var(--secondary-text-color);
    }
    .suggest-add-footer-actions {
      display: flex;
      gap: 8px;
    }
    .explanation {
      margin-top: 12px;
      padding: 12px;
      border-left: 3px solid var(--primary-color);
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.02));
      font-style: italic;
      line-height: 1.5;
    }
    /* v1.12.8 — Specialized card-body renderers (state_shift,
     * physical_device_link, location_proposal). Replaces the
     * generic JSON dump for these v1.7+ insight payloads. */
    .state-shift-summary {
      margin: 12px 0;
      padding: 12px;
      border: 1px solid var(--divider-color, #e0e0e0);
      border-radius: 4px;
    }
    .state-shift-line {
      display: flex;
      gap: 12px;
      padding: 4px 0;
    }
    .state-shift-label {
      min-width: 140px;
      color: var(--secondary-text-color);
      font-weight: 600;
    }
    .state-shift-value {
      font-family: monospace;
    }
    .device-link-pair {
      margin: 12px 0;
      padding: 16px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.02));
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 12px;
    }
    .device-link-eid {
      font-family: monospace;
      padding: 4px 8px;
      background: var(--card-background-color, white);
      border: 1px solid var(--divider-color, #e0e0e0);
      border-radius: 3px;
    }
    .device-link-arrow {
      font-size: 1.4em;
      color: var(--primary-color);
    }
    .location-proposal-summary {
      margin: 12px 0;
      padding: 12px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.02));
      border-radius: 4px;
      line-height: 1.5;
    }
    .location-alt-list {
      margin: 8px 0 0;
      padding-left: 20px;
    }
    .location-alt-list li {
      padding: 2px 0;
    }
    .location-proposal-note {
      margin-top: 12px;
      padding: 8px 12px;
      background: rgba(33, 150, 243, 0.1);
      border-left: 3px solid var(--info-color, #2196f3);
      border-radius: 3px;
      font-size: 0.9em;
    }
    .explain-row {
      display: flex;
      gap: 8px;
      margin-top: 12px;
      flex-wrap: wrap;
    }

    /* v1.5.11 — Setup-guide dialog body for setup_quality insights. */
    .setup-steps {
      display: flex;
      flex-direction: column;
      gap: 10px;
      margin-top: 8px;
    }
    /* v1.2.16 — audit dialog body components */
    .audit-automation-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 12px;
      padding: 10px 12px;
      background: var(--secondary-background-color, #f5f5f5);
      border-radius: 6px;
    }
    .audit-automation-name {
      font-weight: 500;
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .audit-advice {
      margin-top: 12px;
      padding: 8px 12px;
      background: var(--info-color-background, rgba(33, 150, 243, 0.08));
      border-left: 3px solid var(--info-color, #2196f3);
      border-radius: 4px;
      font-size: 0.92em;
      color: var(--primary-text-color);
    }
    .audit-findings {
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .audit-finding {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      padding: 8px 0;
      border-top: 1px solid var(--divider-color, #e0e0e0);
    }
    .audit-finding:first-child {
      border-top: none;
    }
    .audit-finding-icon {
      flex: 0 0 auto;
      font-size: 1.1em;
      line-height: 1.3;
    }
    .audit-finding-text {
      flex: 1;
      line-height: 1.35;
    }
    .audit-finding-action {
      flex: 0 0 auto;
      font-size: 0.85em;
      color: var(--primary-color, #4c6ef5);
      text-decoration: none;
      white-space: nowrap;
      align-self: center;
    }
    .audit-finding-action:hover {
      text-decoration: underline;
    }
    .audit-entity-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    @media (max-width: 600px) {
      .audit-entity-grid {
        grid-template-columns: 1fr;
      }
    }
    .audit-entity-label {
      font-size: 0.85em;
      color: var(--secondary-text-color);
      font-weight: 500;
      margin-bottom: 4px;
    }
    .audit-entity-pills {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
    .audit-entity-pill {
      padding: 3px 8px;
      background: var(--secondary-background-color, #f5f5f5);
      border-radius: 12px;
      font-size: 0.85em;
      font-family: var(--code-font-family, monospace);
    }
    .audit-entity-pill.is-silent {
      background: rgba(244, 67, 54, 0.08);
      color: var(--error-color, #c62828);
    }
    .audit-entity-pill .silent-dot {
      color: var(--error-color, #c62828);
    }
    .audit-related {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .audit-related-link {
      color: var(--primary-color, #4c6ef5);
      text-decoration: none;
      font-size: 0.92em;
    }
    .audit-related-link:hover {
      text-decoration: underline;
    }
    .audit-raw-payload {
      margin-top: 16px;
    }
    .audit-raw-payload summary {
      cursor: pointer;
      font-size: 0.85em;
      color: var(--secondary-text-color);
    }
    .audit-raw-payload pre {
      max-height: 240px;
      overflow: auto;
      font-size: 0.78em;
      background: var(--code-editor-background-color, var(--secondary-background-color, #f5f5f5));
      padding: 8px;
      border-radius: 4px;
      margin-top: 6px;
    }
    .setup-step {
      border: 1px solid var(--divider-color, #e0e0e0);
      border-left: 4px solid var(--divider-color, #e0e0e0);
      border-radius: 6px;
      padding: 10px 12px;
      background: var(--card-background-color, #fff);
    }
    .setup-step--ok { border-left-color: var(--success-color, #4caf50); }
    .setup-step--warn { border-left-color: var(--warning-color, #ef6c00); }
    .setup-step--todo { border-left-color: var(--error-color, #c62828); }
    .setup-step-header {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 500;
    }
    .setup-step-tier {
      font-size: 0.85em;
      padding: 2px 8px;
      border-radius: 12px;
      background: var(--secondary-background-color, #f5f5f5);
      color: var(--secondary-text-color, #555);
      white-space: nowrap;
    }
    .setup-step-name {
      font-size: 1em;
      color: var(--primary-text-color);
    }
    .setup-step-advice {
      margin-top: 6px;
      color: var(--secondary-text-color, #555);
      font-size: 0.92em;
      line-height: 1.4;
    }
    .setup-step-scenarios {
      margin-top: 8px;
      font-size: 0.9em;
    }
    .setup-step-scenarios summary {
      cursor: pointer;
      color: var(--primary-color);
      user-select: none;
    }
    .setup-step-scenarios ul {
      margin: 6px 0 0;
      padding-left: 18px;
      color: var(--secondary-text-color, #555);
    }
    .setup-step-scenarios li {
      margin: 2px 0;
    }
    .setup-step-action {
      margin-top: 10px;
    }
    .setup-step-action .action {
      display: inline-block;
      text-decoration: none;
    }
    .setup-step-note {
      margin-top: 8px;
      padding: 6px 8px;
      background: var(--secondary-background-color, #f5f5f5);
      border-radius: 4px;
      font-size: 0.88em;
      color: var(--secondary-text-color, #555);
      font-style: italic;
    }
    /* Banner shown when the open setup_quality insight is from an
       older detector version (no setup_steps in the payload) — gives
       the user a real button to re-scan instead of dead text. */
    .setup-stale-banner {
      margin-top: 16px;
      padding: 12px;
      border-radius: 6px;
      background: var(--warning-background-color, rgba(255, 152, 0, 0.08));
      border-left: 3px solid var(--warning-color, #ef6c00);
      font-size: 0.92em;
      color: var(--primary-text-color);
    }
    .setup-stale-banner strong {
      display: block;
      margin-bottom: 4px;
    }
    .setup-stale-action {
      margin-top: 10px;
    }

    .refined-banner {
      padding: 10px 12px;
      background: rgba(76, 175, 80, 0.15);
      border-left: 3px solid var(--success-color, #4caf50);
      border-radius: 4px;
      margin-bottom: 12px;
      font-size: 0.9em;
    }
    .refined-banner strong {
      display: block;
      margin-bottom: 4px;
      color: var(--success-color, #2e7d32);
    }
    .diff-list {
      list-style: none;
      padding: 0;
      margin: 8px 0 0;
      font-family: var(--code-font-family, monospace);
      font-size: 0.85em;
    }
    .diff-list li {
      padding: 2px 0;
    }
    .diff-add { color: var(--success-color, #2e7d32); }
    .diff-remove { color: var(--error-color, #c62828); }
    .diff-change { color: var(--warning-color, #ef6c00); }

    /* Side-by-side YAML compare for refined preview */
    .compare {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin: 12px 0;
    }
    .compare-col h5 {
      margin: 0 0 6px;
      font-size: 0.8em;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--secondary-text-color);
    }
    .compare-col pre {
      max-height: 300px;
      overflow: auto;
      margin: 0;
      padding: 10px;
      background: var(--code-background-color, rgba(0, 0, 0, 0.04));
      border-radius: 6px;
      font-size: 0.78em;
      line-height: 1.4;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .compare-col.refined pre {
      border-left: 3px solid var(--success-color, #4caf50);
    }
    @media (max-width: 720px) {
      .compare {
        grid-template-columns: 1fr;
      }
    }

    /* Redaction preview ("What gets sent?") panel */
    .preview {
      margin-top: 12px;
      padding: 10px 12px;
      border-left: 3px solid var(--info-color, #2196f3);
      background: rgba(33, 150, 243, 0.08);
      border-radius: 4px;
    }
    .preview-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }
    .preview-header strong {
      color: var(--info-color, #1565c0);
    }
    .preview-stats {
      font-size: 0.8em;
      color: var(--secondary-text-color);
      margin-bottom: 8px;
    }
    .preview-stats span {
      margin-right: 12px;
    }
    .preview pre {
      max-height: 240px;
      overflow: auto;
      margin: 0;
      padding: 8px;
      background: var(--code-background-color, rgba(0, 0, 0, 0.04));
      border-radius: 4px;
      font-size: 0.78em;
      line-height: 1.4;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .preview-pseudonyms {
      margin-top: 8px;
      font-size: 0.78em;
      color: var(--secondary-text-color);
    }
    .preview-pseudonyms code {
      font-family: var(--code-font-family, monospace);
      background: var(--code-background-color, rgba(0, 0, 0, 0.04));
      padding: 1px 4px;
      border-radius: 3px;
    }

    /* Follow-up feedback for re-refine */
    .feedback {
      margin-top: 12px;
      padding: 10px 12px;
      border: 1px dashed var(--divider-color, rgba(0, 0, 0, 0.2));
      border-radius: 6px;
    }
    .feedback h5 {
      margin: 0 0 6px;
      font-size: 0.85em;
      color: var(--secondary-text-color);
    }
    .feedback textarea {
      width: 100%;
      box-sizing: border-box;
      min-height: 56px;
      padding: 6px 8px;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.18));
      border-radius: 4px;
      font: inherit;
      background: var(--card-background-color, white);
      color: var(--primary-text-color);
      resize: vertical;
    }
    .feedback textarea:focus {
      outline: none;
      border-color: var(--primary-color);
    }

    /* Inline payload editor (v0.8 phase 3) */
    .payload-edit {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-bottom: 6px;
    }
    .payload-edit button {
      background: none;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.18));
      color: var(--primary-text-color);
      padding: 4px 10px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 0.8em;
    }
    .payload-edit button:hover {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
    }
    textarea.payload-editor {
      width: 100%;
      box-sizing: border-box;
      min-height: 240px;
      max-height: 360px;
      padding: 10px 12px;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.18));
      border-radius: 6px;
      font-family: var(--code-font-family, "SFMono-Regular", Consolas, monospace);
      font-size: 0.82em;
      line-height: 1.5;
      background: var(--code-background-color, rgba(0, 0, 0, 0.04));
      color: var(--primary-text-color);
      resize: vertical;
      white-space: pre;
    }
    textarea.payload-editor:focus {
      outline: none;
      border-color: var(--primary-color);
    }
    textarea.payload-editor.error {
      border-color: var(--error-color, #c62828);
    }
    .payload-error {
      margin-top: 6px;
      padding: 8px 10px;
      background: rgba(244, 67, 54, 0.10);
      color: var(--error-color, #c62828);
      border-radius: 4px;
      font-size: 0.85em;
    }

    /* Rename inputs */
    .rename {
      margin-top: 12px;
      padding: 10px 12px;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      border-radius: 6px;
    }
    .rename h4 {
      margin: 0 0 8px;
      font-size: 0.85em;
      color: var(--secondary-text-color);
    }
    .rename label {
      display: block;
      font-size: 0.78em;
      color: var(--secondary-text-color);
      margin: 6px 0 2px;
    }
    .rename input,
    .rename textarea {
      width: 100%;
      box-sizing: border-box;
      padding: 6px 8px;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.18));
      border-radius: 4px;
      font: inherit;
      background: var(--card-background-color, white);
      color: var(--primary-text-color);
    }
    .rename textarea {
      resize: vertical;
      min-height: 48px;
    }
    .rename input:focus,
    .rename textarea:focus {
      outline: none;
      border-color: var(--primary-color);
    }

    /* Test-actions result panel */
    .test-results {
      margin-bottom: 12px;
      padding: 10px 12px;
      border-radius: 6px;
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
      border-left: 3px solid var(--primary-color);
    }
    .test-results.ok {
      border-left-color: var(--success-color, #4caf50);
      background: rgba(76, 175, 80, 0.10);
    }
    .test-results.fail {
      border-left-color: var(--error-color, #f44336);
      background: rgba(244, 67, 54, 0.08);
    }
    .test-results-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 6px;
      font-weight: 500;
    }
    .test-results-close {
      background: none;
      border: none;
      cursor: pointer;
      font-size: 1.1em;
      color: var(--secondary-text-color);
      line-height: 1;
      padding: 0 4px;
    }
    .test-results ul {
      list-style: none;
      padding: 0;
      margin: 6px 0 0;
      font-size: 0.88em;
    }
    .test-results li {
      padding: 4px 0;
      display: flex;
      gap: 8px;
      align-items: flex-start;
    }
    .test-results .icon {
      flex-shrink: 0;
      width: 1.1em;
      text-align: center;
    }
    .test-results .icon-ok { color: var(--success-color, #2e7d32); }
    .test-results .icon-fail { color: var(--error-color, #c62828); }
    .test-results .icon-skip { color: var(--secondary-text-color); }
    .test-results .meta {
      color: var(--secondary-text-color);
      font-size: 0.85em;
      margin-top: 2px;
    }
    .test-results-error {
      color: var(--error-color, #c62828);
      font-size: 0.85em;
      margin-top: 2px;
    }
    .dialog-footer {
      padding: 12px 20px;
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      display: flex;
      gap: 8px;
      justify-content: flex-end;
      flex-wrap: wrap;
    }
  `; }
    setConfig(config) {
        if (!config) {
            throw new Error("Invalid configuration");
        }
        this._config = config;
    }
    /** Declarative-binding alias for setConfig — lets parents do
     *  `<ha-insights-card .config=${cfg}>` and have Lit reuse the same
     *  element across renders so the card preserves its state (open
     *  modal, in-flight refine, etc). The panel relies on this. */
    set config(value) {
        if (value)
            this.setConfig(value);
    }
    get config() {
        return this._config;
    }
    getCardSize() {
        return Math.min(this._insights.length, this._config.max_rows ?? DEFAULT_MAX_ROWS) + 2;
    }
    /** Lovelace hook — return a visual editor for Edit Card UI. */
    static async getConfigElement() {
        return document.createElement("ha-insights-card-editor");
    }
    /** Lovelace hook — sensible defaults when the user adds a fresh card. */
    static getStubConfig() {
        return {
            title: "HA Insights",
            min_confidence: 0.5,
        };
    }
    connectedCallback() {
        super.connectedCallback();
        window.addEventListener("keydown", this._keydownHandler);
        // Panel dispatches these around its Scan / Purge / Backfill flows
        // so we can show a clean loading state instead of the noisy
        // subscribe-stream rows piling up live + getting re-deduped at the end.
        window.addEventListener("ha-insights-scan-start", this._scanStarted);
        window.addEventListener("ha-insights-refresh", this._refreshFromEvent);
        // v1.2.22: hard-clear on purge (panel dispatches this event after
        // calling ha_insights.purge_observations). Belt-and-braces with
        // the subscribe-stream "purged" handling — works even if the
        // subscribe stream is briefly desynced.
        window.addEventListener("ha-insights-purged", this._handlePurgedEvent);
        this._resizeObserver = new ResizeObserver((entries) => {
            for (const entry of entries) {
                this._updateAutoMaxRows(entry.contentRect.height);
            }
        });
        this._resizeObserver.observe(this);
        // v1.2.13: re-wire on re-mount.
        //
        // Background: v1.2.9 made render `_hello`-gated and removed the
        // `_loading` flag — "data-driven render". `disconnectedCallback`
        // clears `_hello` so a fresh fetch fires on re-mount. The
        // `_wire()` trigger lives in `updated()` keyed on
        // `changedProps.has("hass")`.
        //
        // That works when HA's panel framework drops the element and
        // mounts a fresh one (Lit sets `hass` from scratch → "change").
        // BUT when the framework keeps the SAME element instance and
        // just toggles its connected state (e.g. tab switch / "back from
        // another app"), `hass` keeps its old reference and `updated()`
        // doesn't see a hass-change → `_wire()` never fires → card
        // renders the empty `!_hello` placeholder forever.
        //
        // The defensive recovery: if we have `hass` already AND no
        // `_hello`, fire `_wire()` now. Idempotent — `_wire()` short-
        // circuits if it's already running, and a successful run sets
        // `_hello` so the next reconnect cycle skips the work.
        if (this.hass && !this._hello) {
            void this._wire();
        }
    }
    /** v1.2.8 — timeout-wrap a WS promise so an unrecoverably-hanging
     *  call (post-tab-pause, connection in limbo) can't block the UI
     *  forever. Rejects with a typed error after `timeoutMs` so callers
     *  can show the user a real failure instead of "Loading…" forever.
     *  8s default — generous for a healthy WS, tight enough that users
     *  notice failures within their attention span. */
    static { this._WS_TIMEOUT_MS = 8_000; }
    _withTimeout(promise, label, timeoutMs = HaInsightsCard._WS_TIMEOUT_MS) {
        return Promise.race([
            promise,
            new Promise((_, reject) => window.setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs)),
        ]);
    }
    /** Approximate per-row height — title + meta + padding + border. */
    static { this.ROW_HEIGHT_PX = 72; }
    /** Header consumes a fixed slice; banners/toast eat into the body too. */
    static { this.HEADER_HEIGHT_PX = 60; }
    _updateAutoMaxRows(hostHeight) {
        const available = Math.max(0, hostHeight - HaInsightsCard.HEADER_HEIGHT_PX);
        const rows = Math.max(1, Math.floor(available / HaInsightsCard.ROW_HEIGHT_PX));
        if (rows !== this._autoMaxRows) {
            this._autoMaxRows = rows;
        }
    }
    updated(changedProps) {
        // v1.2.9: trigger initial fetch when hass first arrives. The
        // gate is `!this._hello` — if hello is undefined we haven't
        // successfully talked to the integration yet. Single source of
        // truth: hello-response IS the "we're connected" signal.
        if (changedProps.has("hass") && this.hass && !this._hello) {
            void this._wire();
        }
        if (changedProps.has("_toast") && this._toast) {
            window.clearTimeout(this._toastTimer);
            this._toastTimer = window.setTimeout(() => {
                this._toast = undefined;
            }, 2500);
        }
        if (changedProps.has("_dialogId")) {
            // Lock body scroll while modal is open so the dashboard underneath
            // doesn't move when users scroll the dialog body.
            document.body.style.overflow = this._dialogId ? "hidden" : "";
        }
        if (changedProps.has("_insights")) {
            // v1.1: emit an event the panel listens for so it can refresh its
            // chip-filter options + "Showing X of Y" counters. Bubbles +
            // composed so the panel parent receives it through the shadow DOM.
            this.dispatchEvent(new CustomEvent("insights-loaded", {
                detail: { insights: this._insights },
                bubbles: true,
                composed: true,
            }));
        }
    }
    disconnectedCallback() {
        super.disconnectedCallback();
        window.removeEventListener("keydown", this._keydownHandler);
        window.removeEventListener("ha-insights-scan-start", this._scanStarted);
        window.removeEventListener("ha-insights-refresh", this._refreshFromEvent);
        window.removeEventListener("ha-insights-purged", this._handlePurgedEvent);
        // v1.2.9: resume-listener cleanup removed alongside the
        // visibility handler. Nothing to tear down besides the standard
        // subscribe handle + resize observer.
        document.body.style.overflow = "";
        this._unsub?.();
        this._unsub = undefined;
        // Clear `_hello` so a fresh element instance after a re-mount
        // (HA panel navigation cycle) treats itself as un-fetched and
        // re-runs the initial fetch via updated().
        this._hello = undefined;
        this._resizeObserver?.disconnect();
        this._resizeObserver = undefined;
    }
    async _wire() {
        if (!this.hass)
            return;
        if (this._wiring)
            return; // v1.2.13: re-entry guard
        this._wiring = true;
        // v1.2.8: every WS call gets a timeout. If the call hangs (post-
        // tab-resume, WS-reconnect-in-flight, slow integration startup),
        // we surface a real error after 8s instead of sitting on
        // "Loading…" forever.
        // v1.2.9: no _loading flag to clear. Failures set _error which
        // render() shows as a banner; subsequent retries clear _error
        // on success. The card always renders SOMETHING useful — never
        // a stuck curtain.
        try {
            try {
                this._hello = await this._withTimeout(this.hass.connection.sendMessagePromise({
                    type: "home_insights/hello",
                    card_version: "0.8.2",
                }), "home_insights/hello");
            }
            catch (err) {
                this._error = `Integration not reachable: ${this._asMessage(err)}`;
                return;
            }
            try {
                const result = await this._withTimeout(this.hass.connection.sendMessagePromise({
                    type: "home_insights/list",
                    include_applied: Boolean(this._config.include_applied),
                    include_retired: this._showHistory,
                    include_dismissed: this._showHistory,
                    include_snoozed: this._showHistory,
                }), "home_insights/list");
                this._insights = result.insights ?? [];
                this._error = undefined; // success clears any prior error
            }
            catch (err) {
                this._error = `Could not list insights: ${this._asMessage(err)}`;
                return;
            }
            // Drop any stale subscription from a prior wire cycle (e.g.
            // tab-return re-mount where disconnectedCallback fired the old
            // unsub but the new connect needs a fresh subscribe).
            this._unsub?.();
            this._unsub = undefined;
            try {
                this._unsub = await this._withTimeout(this.hass.connection.subscribeMessage((event) => this._handleEvent(event), { type: "home_insights/subscribe" }), "home_insights/subscribe");
            }
            catch (err) {
                console.warn("ha-insights-card subscribe failed", err);
                // Subscribe is non-fatal — we have list data; the user just
                // won't see live updates until next refresh.
            }
        }
        finally {
            this._wiring = false;
        }
    }
    _handleEvent(event) {
        // `purged` events carry no insight payload — server fires one when
        // the user clicks "Purge all" / calls ha_insights.purge_observations.
        // Drop the entire local list so the panel goes empty live, no
        // manual page refresh needed.
        if (event.action === "purged") {
            this._insights = [];
            if (this._dialogId)
                this._closeDialog();
            return;
        }
        if (!event.insight)
            return;
        // v1.2.22: drop "added" events during the post-purge suppression
        // window. Scans keep running in the background; the user gets a
        // brief moment of empty state before detection resumes. Other
        // event actions (dismissed/snoozed/applied/undone) bypass —
        // they're user-initiated and shouldn't be suppressed.
        if (event.action === "added" && Date.now() < this._suppressAddedUntil) {
            return;
        }
        const next = [...this._insights];
        const idx = next.findIndex((i) => i.id === event.insight.id);
        const wantApplied = Boolean(this._config.include_applied);
        if (event.action === "added") {
            if (idx >= 0)
                next[idx] = event.insight;
            else
                next.unshift(event.insight);
        }
        else if (event.action === "dismissed" ||
            event.action === "snoozed") {
            if (idx >= 0)
                next.splice(idx, 1);
            if (this._dialogId === event.insight.id)
                this._closeDialog();
        }
        else if (event.action === "applied") {
            // If this card includes_applied, keep the row + update with the
            // new applied state; otherwise drop it from the active list.
            if (wantApplied) {
                if (idx >= 0)
                    next[idx] = event.insight;
                else
                    next.unshift(event.insight);
            }
            else if (idx >= 0) {
                next.splice(idx, 1);
                if (this._dialogId === event.insight.id)
                    this._closeDialog();
            }
        }
        else if (event.action === "undone") {
            // Insight is back to active state — keep visible regardless
            if (idx >= 0)
                next[idx] = event.insight;
            else
                next.unshift(event.insight);
        }
        else if (idx >= 0) {
            next[idx] = event.insight;
        }
        this._insights = next;
    }
    /** Optimistic remove — keeps the UX snappy if the subscribe event lags. */
    _removeFromList(id) {
        this._insights = this._insights.filter((i) => i.id !== id);
        if (this._dialogId === id)
            this._closeDialog();
    }
    async _runScanNow() {
        if (!this.hass || this._scanBusy)
            return;
        // home_insights/scan_now WS endpoint awaits actual scan completion
        // and returns counts. call_service was returning the moment the call
        // queued, so the toast said "complete" instantly while the scan was
        // still in flight, with no in-progress feedback.
        this._scanBusy = true;
        this._toast = "Scanning…";
        try {
            const scan = await this.hass.connection.sendMessagePromise({ type: "home_insights/scan_now" });
            const noun = scan.insights_emitted === 1 ? "insight" : "insights";
            this._toast =
                `Scan complete: ${scan.insights_emitted} new ${noun} from ${scan.detectors_run.length} detectors`;
            // Refresh the list so any new insights show up immediately
            try {
                const result = await this.hass.connection.sendMessagePromise({
                    type: "home_insights/list",
                    include_applied: Boolean(this._config.include_applied),
                    include_retired: this._showHistory,
                    include_dismissed: this._showHistory,
                    include_snoozed: this._showHistory,
                });
                this._insights = result.insights ?? [];
            }
            catch {
                // Subscribe events will eventually catch up; non-fatal
            }
        }
        catch (err) {
            this._error = `Scan failed: ${this._asMessage(err)}`;
        }
        finally {
            this._scanBusy = false;
        }
    }
    async _undo(insight, force = false) {
        if (!this.hass)
            return;
        this._busyId = insight.id;
        try {
            const result = await this.hass.connection.sendMessagePromise({
                type: "home_insights/undo",
                insight_id: insight.id,
                force,
            });
            this._toast = result.drift_detected && result.force_used
                ? `Undid ${insight.title} (forced — your edits were lost)`
                : `Undid ${insight.title}`;
        }
        catch (err) {
            const message = this._asMessage(err);
            // Drift error is recoverable — offer force-undo confirmation
            const code = err.code;
            if (code === "drift") {
                const proceed = window.confirm(`${message}\n\nForce undo and lose your manual edits?`);
                if (proceed) {
                    await this._undo(insight, true);
                    return;
                }
            }
            else {
                this._failModal(`Undo failed: ${message}`);
            }
        }
        finally {
            this._busyId = undefined;
        }
    }
    async _apply(insight, refinedPayload) {
        if (!this.hass)
            return;
        // If the user opened the inline payload editor, parse their JSON.
        // Parse errors abort the apply with an inline error in the modal —
        // the modal stays open so they can fix and retry.
        let editedPayload;
        const editedSource = this._payloadEditsById.get(insight.id);
        if (editedSource !== undefined
            && this._editingPayloadFor.has(insight.id)) {
            try {
                const parsed = JSON.parse(editedSource);
                if (typeof parsed !== "object"
                    || parsed === null
                    || Array.isArray(parsed)) {
                    throw new Error("Edited payload must be a JSON object");
                }
                editedPayload = parsed;
                const errs = new Map(this._payloadParseErrorById);
                errs.delete(insight.id);
                this._payloadParseErrorById = errs;
            }
            catch (err) {
                const errs = new Map(this._payloadParseErrorById);
                errs.set(insight.id, `Invalid JSON: ${this._asMessage(err)}`);
                this._payloadParseErrorById = errs;
                return;
            }
        }
        this._busyId = insight.id;
        try {
            // Edit precedence: explicit edited payload > refined > original.
            // Rename block layers on top of whichever base the user is using.
            const basePayload = editedPayload ?? refinedPayload ?? insight.payload;
            const edits = this._renameEdits.get(insight.id);
            const renamed = edits && (edits.alias !== undefined || edits.description !== undefined);
            const useOverride = editedPayload || refinedPayload || renamed;
            const override = useOverride
                ? { ...basePayload, ...(edits ?? {}) }
                : undefined;
            const message = {
                type: "home_insights/apply",
                insight_id: insight.id,
            };
            if (override)
                message.payload_override = override;
            await this.hass.connection.sendMessagePromise(message);
            // Cleanup local state
            this._refinedById.delete(insight.id);
            this._renameEdits.delete(insight.id);
            this._resetRefineConversation(insight.id);
            this._removeFromList(insight.id);
            const label = editedPayload
                ? "Applied (edited)"
                : refinedPayload
                    ? "Applied refined"
                    : renamed
                        ? "Applied (renamed)"
                        : "Applied";
            this._toast = `${label}: ${insight.title}`;
            // Cleanup edit state on successful apply
            const editing = new Set(this._editingPayloadFor);
            editing.delete(insight.id);
            this._editingPayloadFor = editing;
            const drafts = new Map(this._payloadEditsById);
            drafts.delete(insight.id);
            this._payloadEditsById = drafts;
        }
        catch (err) {
            this._failModal(`Apply failed: ${this._asMessage(err)}`);
        }
        finally {
            this._busyId = undefined;
        }
    }
    _togglePayloadEdit(insight, basePayload) {
        const editing = new Set(this._editingPayloadFor);
        if (editing.has(insight.id)) {
            editing.delete(insight.id);
            // Discard the in-progress edit
            const drafts = new Map(this._payloadEditsById);
            drafts.delete(insight.id);
            this._payloadEditsById = drafts;
            const errs = new Map(this._payloadParseErrorById);
            errs.delete(insight.id);
            this._payloadParseErrorById = errs;
        }
        else {
            editing.add(insight.id);
            // Seed from the base payload the user is currently looking at:
            // refined when in refined-preview view, else the original.
            const seed = basePayload ?? insight.payload;
            const drafts = new Map(this._payloadEditsById);
            drafts.set(insight.id, JSON.stringify(seed, null, 2));
            this._payloadEditsById = drafts;
        }
        this._editingPayloadFor = editing;
    }
    _onPayloadEditInput(insightId, e) {
        const value = e.target.value;
        const drafts = new Map(this._payloadEditsById);
        drafts.set(insightId, value);
        this._payloadEditsById = drafts;
        // Clear stale parse error so user gets immediate feedback on next Apply
        if (this._payloadParseErrorById.has(insightId)) {
            const errs = new Map(this._payloadParseErrorById);
            errs.delete(insightId);
            this._payloadParseErrorById = errs;
        }
    }
    _onRenameField(insightId, field, e) {
        const value = e.target.value;
        const next = new Map(this._renameEdits);
        const entry = { ...(next.get(insightId) ?? {}) };
        entry[field] = value;
        next.set(insightId, entry);
        this._renameEdits = next;
    }
    _renderRename(insight, refined) {
        const base = refined?.payload ?? insight.payload;
        const edits = this._renameEdits.get(insight.id) ?? {};
        const alias = edits.alias ?? base.alias ?? "";
        const description = edits.description ?? base.description ?? "";
        return b `
      <div class="rename">
        <h4>Customize</h4>
        <label for="ha-insights-alias-${insight.id}">Alias</label>
        <input
          id="ha-insights-alias-${insight.id}"
          type="text"
          .value=${alias}
          @input=${(e) => this._onRenameField(insight.id, "alias", e)}
        />
        <label for="ha-insights-desc-${insight.id}">Description</label>
        <textarea
          id="ha-insights-desc-${insight.id}"
          .value=${description}
          @input=${(e) => this._onRenameField(insight.id, "description", e)}
        ></textarea>
      </div>
    `;
    }
    /** Pick the right error sink. Modal-open errors stay scoped; the rest go
     *  to the main card banner. */
    _failModal(message) {
        if (this._dialogId) {
            this._modalError = message;
        }
        else {
            this._error = message;
        }
    }
    async _dismiss(insight) {
        if (!this.hass)
            return;
        this._busyId = insight.id;
        try {
            await this.hass.connection.sendMessagePromise({
                type: "home_insights/dismiss",
                insight_id: insight.id,
            });
            this._removeFromList(insight.id);
            this._toast = "Dismissed";
        }
        catch (err) {
            this._failModal(`Dismiss failed: ${this._asMessage(err)}`);
        }
        finally {
            this._busyId = undefined;
        }
    }
    async _snooze(insight) {
        if (!this.hass)
            return;
        const until = new Date();
        until.setDate(until.getDate() + 7);
        this._busyId = insight.id;
        try {
            await this.hass.connection.sendMessagePromise({
                type: "home_insights/snooze",
                insight_id: insight.id,
                until: until.toISOString(),
            });
            this._removeFromList(insight.id);
            this._toast = "Snoozed for 7 days";
        }
        catch (err) {
            this._failModal(`Snooze failed: ${this._asMessage(err)}`);
        }
        finally {
            this._busyId = undefined;
        }
    }
    /** v1.2.28: Retire an insight — the third lifecycle option alongside
     *  Dismiss / Snooze. Different semantics: Retire means "I've decided
     *  NOT to automate this pattern" and survives re-detections of the
     *  same fingerprint until the user explicitly un-retires through the
     *  history view. Stays out of the default list. */
    async _retire(insight) {
        if (!this.hass)
            return;
        this._busyId = insight.id;
        try {
            await this.hass.connection.sendMessagePromise({
                type: "home_insights/retire",
                insight_id: insight.id,
            });
            if (!this._showHistory) {
                this._removeFromList(insight.id);
            }
            this._toast = "Retired — won't suggest again";
        }
        catch (err) {
            this._failModal(`Retire failed: ${this._asMessage(err)}`);
        }
        finally {
            this._busyId = undefined;
        }
    }
    /** v1.2.28: Reverse a prior Retire decision. Only reachable from the
     *  history view (where retired insights are visible). */
    async _unretire(insight) {
        if (!this.hass)
            return;
        this._busyId = insight.id;
        try {
            await this.hass.connection.sendMessagePromise({
                type: "home_insights/unretire",
                insight_id: insight.id,
            });
            this._toast = "Un-retired — back in the suggestion queue";
            // Force a refresh so the row re-emerges in the default list
            // (history toggle stays where it was).
            window.dispatchEvent(new CustomEvent("ha-insights-refresh"));
        }
        catch (err) {
            this._failModal(`Un-retire failed: ${this._asMessage(err)}`);
        }
        finally {
            this._busyId = undefined;
        }
    }
    /** v1.2.28: Toggle the history view. Re-fetches the list with the
     *  retired/dismissed/snoozed surfaces opted in (or out). */
    async _toggleHistory() {
        this._showHistory = !this._showHistory;
        if (!this.hass)
            return;
        try {
            const result = await this._withTimeout(this.hass.connection.sendMessagePromise({
                type: "home_insights/list",
                include_applied: Boolean(this._config.include_applied),
                include_retired: this._showHistory,
                include_dismissed: this._showHistory,
                include_snoozed: this._showHistory,
            }), "home_insights/list (history)");
            this._insights = result.insights ?? [];
        }
        catch (err) {
            this._failModal(`Couldn't load history: ${this._asMessage(err)}`);
        }
    }
    /** Preview the deterministic-fix audit (Phase B.5) as a side-by-
     *  side diff. NO LLM call — the refined YAML is already in the
     *  insight payload from when the detector ran. We just need to
     *  pull the current YAML so the diff has both sides.
     *
     *  Cost: one cheap WS call to home_insights/get_automation,
     *  zero LLM tokens. Lets users see "here's what would change if
     *  I click Apply" without committing. */
    async _previewDeterministicAudit(insight) {
        if (!this.hass)
            return;
        const payload = insight.payload || {};
        const auditMeta = payload._audit || {};
        const automationId = auditMeta.automation_id ||
            payload.id ||
            "";
        const alias = auditMeta.automation_alias ||
            payload.alias ||
            automationId;
        const fixSummaries = Array.isArray(auditMeta.fix_summaries)
            ? auditMeta.fix_summaries
            : [];
        // The refined automation lives at the top level of the payload
        // (Phase B.5 spreads it). Strip the `_audit` metadata so we
        // diff just the YAML the user would actually apply.
        const refinedConfig = {};
        for (const [k, v] of Object.entries(payload)) {
            if (k === "_audit")
                continue;
            refinedConfig[k] = v;
        }
        // Prefer the backend's pre-serialized YAML (now stored on the
        // insight payload as _audit.refined_yaml_text). Falls back to a
        // client-side JSON dump for backwards compatibility with older
        // stored audit insights.
        const backendRefinedYaml = typeof auditMeta.refined_yaml_text === "string"
            ? auditMeta.refined_yaml_text
            : "";
        try {
            const result = await this.hass.connection.sendMessagePromise({
                type: "home_insights/get_automation",
                automation_id: automationId,
            });
            const refinedYaml = backendRefinedYaml || JSON.stringify(refinedConfig, null, 2);
            this._refineAutomationModal = {
                automationId,
                alias,
                originalYaml: result.yaml,
                feedback: "",
                busy: false,
                refinedYaml,
                refinedConfig,
                rationale: "Deterministic fix — no LLM was called. " +
                    (fixSummaries.length > 0
                        ? fixSummaries.join(" ")
                        : "Review the diff below; Apply writes the refined YAML to your automation."),
                diffSummary: fixSummaries,
                refinedSource: "deterministic",
                auditInsightId: insight.id,
            };
        }
        catch (err) {
            this._failModal(`Preview failed: ${this._asMessage(err)}`);
        }
    }
    /** Two-stage refinement: take the current modal's refined YAML
     *  (from a 📋 Preview) as the new starting point, then ask the
     *  LLM to refine further with any additional user feedback typed
     *  in the textarea. The deterministic fixes are preserved as the
     *  baseline — the LLM builds on top instead of redoing them. */
    async _refineFurtherWithLlm() {
        const m = this._refineAutomationModal;
        if (!this.hass || !m || !m.auditInsightId || !m.refinedConfig)
            return;
        this._refineAutomationModal = { ...m, busy: true, error: undefined };
        try {
            const result = await this.hass.connection.sendMessagePromise({
                type: "home_insights/audit_suggest",
                insight_id: m.auditInsightId,
                seed_config: m.refinedConfig,
                extra_feedback: m.feedback || "",
                ...(this._config.audit_depth
                    ? { analysis_depth: this._config.audit_depth }
                    : {}),
            });
            if (!result.refined_yaml) {
                throw new Error("LLM response missing refined_yaml. The integration may "
                    + "need a reload to pick up the two-stage refinement code.");
            }
            this._refineAutomationModal = {
                ...m,
                // Baseline is now the algorithm's output (what the LLM was
                // given). Refined is the LLM's further refinement.
                originalYaml: result.original_yaml ?? m.refinedYaml ?? "",
                refinedYaml: result.refined_yaml,
                refinedConfig: result.refined_config,
                rationale: result.rationale,
                diffSummary: result.diff_summary ?? [],
                bytesSent: result.bytes_sent,
                bytesReceived: result.bytes_received,
                busy: false,
                refinedSource: "stage-two",
            };
        }
        catch (err) {
            this._refineAutomationModal = {
                ...this._refineAutomationModal,
                busy: false,
                error: this._asMessage(err),
            };
        }
    }
    /** Ask the LLM for concrete YAML edits on an audit insight whose
     *  findings don't have a deterministic fix. Reuses the
     *  refine-existing-automation modal to render the result. Cached
     *  on the backend by (yaml_hash + observation_kinds_hash) so a
     *  repeated click on the same row costs zero tokens. */
    /** v1.2.27 — Suggested-Additions, deterministic surface.
     *
     *  Fetches candidate entities from the backend (`home_insights/
     *  suggest_additions`) and opens the modal with HIGH/MEDIUM/LOW
     *  tier-grouped checkboxes. HIGH candidates are pre-selected;
     *  MEDIUM/LOW remain unchecked. User picks, clicks Apply → calls
     *  `home_insights/apply` with `additional_entity_ids`.
     *
     *  Local-first feature — no LLM tokens spent regardless of card
     *  configuration. Cross-domain candidates outside the 21 known
     *  turn_on/off domains come back as `unhandled_entity_ids` from
     *  the apply call; we surface a toast with an offer to escalate
     *  to LLM Refine for the right service call.
     */
    async _openSuggestAddDialog(insight) {
        if (!this.hass)
            return;
        this._suggestAddBusy = insight.id;
        try {
            const result = await this._withTimeout(this.hass.connection.sendMessagePromise({
                type: "home_insights/suggest_additions",
                insight_id: insight.id,
            }), "home_insights/suggest_additions");
            if (!result.candidates || result.candidates.length === 0) {
                this._toast =
                    "No candidate additions found — no nearby entities " +
                        "match the criteria for this automation.";
                return;
            }
            // Pre-select HIGH-tier candidates by default (the recommendation).
            // MEDIUM is visible but unchecked; LOW is collapsed under "Show
            // more" in the modal renderer. User overrides freely.
            const preselected = new Set(result.candidates
                .filter((c) => c.tier === "HIGH")
                .map((c) => c.entity_id));
            this._suggestAddDialog = {
                insightId: insight.id,
                insightTitle: this._displayTitle(insight),
                candidates: result.candidates,
                requiredEids: result.required_entity_ids ?? [],
                selected: preselected,
                applying: false,
            };
        }
        catch (err) {
            this._toast = `Couldn't load candidates: ${this._asMessage(err)}`;
        }
        finally {
            this._suggestAddBusy = null;
        }
    }
    _toggleSuggestAddSelection(eid) {
        if (!this._suggestAddDialog)
            return;
        const next = new Set(this._suggestAddDialog.selected);
        if (next.has(eid)) {
            next.delete(eid);
        }
        else {
            next.add(eid);
        }
        this._suggestAddDialog = {
            ...this._suggestAddDialog,
            selected: next,
        };
    }
    _closeSuggestAddDialog() {
        this._suggestAddDialog = undefined;
    }
    async _applySuggestedAdditions() {
        if (!this.hass || !this._suggestAddDialog)
            return;
        const dialog = this._suggestAddDialog;
        const chosen = Array.from(dialog.selected);
        if (chosen.length === 0) {
            this._suggestAddDialog = {
                ...dialog,
                error: "Select at least one candidate to apply.",
            };
            return;
        }
        this._suggestAddDialog = { ...dialog, applying: true, error: undefined };
        try {
            const result = await this._withTimeout(this.hass.connection.sendMessagePromise({
                type: "home_insights/apply",
                insight_id: dialog.insightId,
                additional_entity_ids: chosen,
            }), "home_insights/apply (additions)");
            const applied = chosen.length - (result.unhandled_entity_ids?.length ?? 0);
            const unhandled = result.unhandled_entity_ids ?? [];
            this._closeSuggestAddDialog();
            if (unhandled.length > 0) {
                this._toast =
                    `Added ${applied} ${applied === 1 ? "entity" : "entities"}. ` +
                        `${unhandled.length} cross-domain ${unhandled.length === 1 ? "candidate" : "candidates"} ` +
                        "need LLM Refine to add (different service call). " +
                        "Open Refine on the insight to handle them.";
            }
            else {
                this._toast = `Added ${applied} ${applied === 1 ? "entity" : "entities"} to the automation.`;
            }
            // Force a refresh so the row reflects the applied state.
            window.dispatchEvent(new CustomEvent("ha-insights-refresh"));
        }
        catch (err) {
            this._suggestAddDialog = {
                ...dialog,
                applying: false,
                error: this._asMessage(err),
            };
        }
    }
    /** v1.2.27 — Render the Suggested-Additions modal. Groups candidates by
     *  tier (HIGH/MEDIUM/LOW) with green/amber/grey chips matching the
     *  confidence-colour convention used elsewhere in the card. Checkboxes
     *  are pre-selected for HIGH-tier rows by `_openSuggestAddDialog`; the
     *  user toggles freely. Apply calls `home_insights/apply` with the
     *  chosen entity_ids tacked onto the existing automation. */
    _renderSuggestAddDialog() {
        const dialog = this._suggestAddDialog;
        if (!dialog)
            return A;
        const grouped = {
            HIGH: [],
            MEDIUM: [],
            LOW: [],
        };
        for (const c of dialog.candidates) {
            const tier = c.tier in grouped
                ? c.tier
                : "LOW";
            grouped[tier].push(c);
        }
        const renderTierGroup = (tier, label, blurb) => {
            const items = grouped[tier];
            if (items.length === 0)
                return A;
            return b `
        <div class="suggest-add-group">
          <div class="suggest-add-group-header">
            <span class="suggest-add-tier-chip suggest-add-tier-${tier.toLowerCase()}">
              ${label}
            </span>
            <span class="suggest-add-group-blurb">${blurb}</span>
          </div>
          ${items.map((c) => {
                const checked = dialog.selected.has(c.entity_id);
                return b `
              <label class="suggest-add-row">
                <input
                  type="checkbox"
                  ?checked=${checked}
                  ?disabled=${dialog.applying}
                  @change=${() => this._toggleSuggestAddSelection(c.entity_id)}
                />
                <div class="suggest-add-row-text">
                  <code class="suggest-add-eid">${c.entity_id}</code>
                  ${c.reasons.length > 0
                    ? b `<div class="suggest-add-reasons">
                        ${c.reasons.join(" · ")}
                      </div>`
                    : A}
                </div>
              </label>
            `;
            })}
        </div>
      `;
        };
        const selectedCount = dialog.selected.size;
        const totalCount = dialog.candidates.length;
        return b `
      <div class="dialog-backdrop" @click=${this._closeSuggestAddDialog}>
        <div
          class="dialog"
          @click=${(e) => e.stopPropagation()}
        >
          <div class="dialog-header">
            <div class="dialog-title">
              💡 Suggest additions — ${dialog.insightTitle}
            </div>
            <button
              class="dialog-close"
              aria-label="Close"
              ?disabled=${dialog.applying}
              @click=${this._closeSuggestAddDialog}
            >
              ×
            </button>
          </div>
          <div class="dialog-body">
            <div class="suggest-add-intro">
              Pick entities to add to this automation's action block.
              ${dialog.requiredEids.length > 0
            ? b `The existing
                    <strong>${dialog.requiredEids.length}</strong>
                    ${dialog.requiredEids.length === 1
                ? "entity"
                : "entities"}
                    in the automation
                    ${dialog.requiredEids.length === 1 ? "is" : "are"}
                    preserved.`
            : A}
            </div>
            ${dialog.error
            ? b `<div class="suggest-add-error">${dialog.error}</div>`
            : A}
            ${renderTierGroup("HIGH", "HIGH", "Strong match — pre-selected. Coactivators or same-domain device-mates.")}
            ${renderTierGroup("MEDIUM", "MEDIUM", "Worth considering — area-mates or cross-domain device-mates.")}
            ${renderTierGroup("LOW", "LOW", "Weak match — domain-siblings or cross-domain area-mates.")}
            ${totalCount === 0
            ? b `<div class="suggest-add-empty">
                  No candidate additions found.
                </div>`
            : A}
          </div>
          <div class="suggest-add-footer">
            <div class="suggest-add-count">
              ${selectedCount} of ${totalCount} selected
            </div>
            <div class="suggest-add-footer-actions">
              <button
                class="action"
                ?disabled=${dialog.applying}
                @click=${this._closeSuggestAddDialog}
              >
                Cancel
              </button>
              <button
                class="action primary ${dialog.applying ? "busy-pulse" : ""}"
                ?disabled=${dialog.applying || selectedCount === 0}
                @click=${this._applySuggestedAdditions}
              >
                ${dialog.applying
            ? "Applying…"
            : `Apply ${selectedCount} to automation`}
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
    }
    async _runAuditSuggest(insight) {
        if (!this.hass)
            return;
        this._auditSuggestBusy = insight.id;
        try {
            const result = await this.hass.connection.sendMessagePromise({
                type: "home_insights/audit_suggest",
                insight_id: insight.id,
                // Per-call override of the integration's audit_analysis_depth
                // OptionsFlow setting. Backend resolves: per-call > options
                // > "concise" default.
                ...(this._config.audit_depth
                    ? { analysis_depth: this._config.audit_depth }
                    : {}),
            });
            // Loud-fail guard: if the backend didn't ship original_yaml /
            // refined_yaml (only refined_config), the integration is
            // running stale Python and the modal would open blank. Throw
            // here so the user sees the persistent notification + banner,
            // not an empty dialog.
            if (!result.original_yaml || !result.refined_yaml) {
                throw new Error("Audit suggest response is missing YAML fields. The integration "
                    + "needs a reload: Settings → Devices & Services → HA Insights → "
                    + "⋮ → Reload. Python caches old code until that's done.");
            }
            // Render via the existing refine-existing-automation modal so
            // we don't ship a second YAML diff UI. Backend now serializes
            // both sides as real YAML so the side-by-side diff is readable.
            this._refineAutomationModal = {
                automationId: result.automation_id,
                alias: result.alias ?? "",
                originalYaml: result.original_yaml,
                feedback: "",
                busy: false,
                refinedYaml: result.refined_yaml,
                refinedConfig: result.refined_config,
                rationale: result.rationale,
                diffSummary: result.diff_summary ?? [],
                bytesSent: result.bytes_sent,
                bytesReceived: result.bytes_received,
            };
        }
        catch (err) {
            const message = this._asMessage(err);
            // Two-channel visibility: card error banner AND an HA persistent
            // notification. A silent button reset is what landed the user
            // here previously — never again. Notification stays until the
            // user dismisses it; banner is per-card-render.
            this._failModal(`Suggest failed: ${message}`);
            void this._postPersistentNotification("HA Insights: 🤖 Suggest failed", `Could not suggest improvements for "${insight.title}": ${message}\n\n`
                + "If this is the AttemptAudit/to_dict error, reload the integration "
                + "(Settings → Devices & Services → HA Insights → ⋮ → Reload) — "
                + "Python caches the old code until reload.", `ha_insights_suggest_fail_${insight.id}`);
        }
        finally {
            this._auditSuggestBusy = null;
        }
    }
    /** Fire HA's persistent_notification.create so a failure isn't
     *  hidden in the card's banner if the user scrolled away.
     *  Notification appears under the bell icon in the top bar AND
     *  in Settings → Notifications. */
    async _postPersistentNotification(title, message, notificationId) {
        if (!this.hass)
            return;
        try {
            await this.hass.connection.sendMessagePromise({
                type: "call_service",
                domain: "persistent_notification",
                service: "create",
                service_data: {
                    title,
                    message,
                    notification_id: notificationId,
                },
            });
        }
        catch {
            // Notification fallback is best-effort; banner already has it.
        }
    }
    /** v1.10.4: pull the primary entity_id out of an insight's fingerprint.
     *  Mirrors the server-side enrichment in ws_api.ws_list which prefers
     *  `entity_id`, falls back to `follower_entity_id`, then
     *  `leader_entity_id`. Returns null when the insight is a cohort
     *  representative or otherwise doesn't pin a single entity. */
    _primaryEntityId(insight) {
        const fp = insight.fingerprint;
        if (!fp)
            return null;
        for (const k of [
            "entity_id",
            "follower_entity_id",
            "leader_entity_id",
            "target_entity_id",
        ]) {
            const v = fp[k];
            if (typeof v === "string" && v.includes("."))
                return v;
        }
        return null;
    }
    /** Collect EVERY entity_id referenced by this insight. Includes the
     *  primary entity, any peer/leader/follower from the fingerprint, AND
     *  cohort_members for cohort insights. De-duplicated, sorted for
     *  stable display order. */
    _allReferencedEntities(insight) {
        const seen = new Set();
        const fp = insight.fingerprint;
        if (fp) {
            for (const k of [
                "entity_id",
                "leader_entity_id",
                "follower_entity_id",
                "target_entity_id",
                "peer_entity_id",
            ]) {
                const v = fp[k];
                if (typeof v === "string" && v.includes("."))
                    seen.add(v);
            }
        }
        for (const m of insight.cohort_members ?? []) {
            if (typeof m === "string" && m.includes("."))
                seen.add(m);
        }
        return Array.from(seen).sort();
    }
    /** v1.10.7: open the looping-identify modal for an insight.
     *
     *  Pre-v1.10.7 we fired the identifier once and showed a toast — but
     *  many devices flash too quickly to spot, the toast disappeared
     *  while users were still searching, and multi-entity insights
     *  (cohorts, lagged-correlation pairs, physical-device-link pairs)
     *  only identified one of the entities.
     *
     *  v1.10.7 flow:
     *    1. Open a modal listing EVERY referenced entity with a checkbox
     *    2. Fire identify on all checked entities immediately
     *    3. Re-fire every 5 seconds (Find My iPhone style)
     *    4. User unchecks entities as they find each physical device
     *    5. Click "Found it!" or "Stop" → tear down + close
     *    6. Counter increments per cycle so user knows it's still running
     */
    async _identifyEntity(insight) {
        if (!this.hass)
            return;
        const entities = this._allReferencedEntities(insight);
        if (entities.length === 0) {
            this._failModal("No identifiable entities in this insight's fingerprint.");
            return;
        }
        this._identifyAllEntities = entities;
        this._identifyEntityId = entities[0]; // legacy single-entity field
        this._identifyMethod = "";
        this._identifyCount = 0;
        this._identifyError = "";
        this._identifyOpen = true;
        if (entities.length === 1) {
            // Single-entity insight: capture + auto-start so the user
            // doesn't have to click a row. Same UX as v1.10.5.
            this._captureEntityState(entities[0]);
            this._identifySelected = new Set(entities);
            if (this._identifyTimer != null)
                clearInterval(this._identifyTimer);
            await this._fireIdentifyOnce();
            this._identifyTimer = setInterval(() => void this._fireIdentifyOnce(), 5000);
        }
        else {
            // v1.10.9: multi-entity insights open with NOTHING selected.
            // User picks which entity to identify first (1-at-a-time by
            // default; toggle to fire-all is available). Prevents stampede
            // strobing of 12 cohort lights at once, which is disruptive
            // with Circadian Lighting / auto-off automations.
            this._identifySelected = new Set();
            if (this._identifyTimer != null) {
                clearInterval(this._identifyTimer);
                this._identifyTimer = null;
            }
        }
    }
    /** Fire the identifier ONCE. Used by both the initial click and the
     *  recurring timer. Increments _identifyCount on success, sets
     *  _identifyError on failure (which stops the loop). */
    async _fireIdentifyOnce() {
        if (!this.hass || this._identifySelected.size === 0)
            return;
        // Fire identify on every CHECKED entity in parallel. Errors on
        // individual entities accumulate into _identifyError but don't
        // stop the loop — the other entities may still be identifying
        // successfully.
        const entities = Array.from(this._identifySelected);
        const results = await Promise.allSettled(entities.map((entityId) => this.hass.connection.sendMessagePromise({
            type: "home_insights/identify_entity",
            entity_id: entityId,
        })));
        const errors = [];
        for (let i = 0; i < results.length; i++) {
            const r = results[i];
            if (r.status === "fulfilled") {
                if (r.value.method)
                    this._identifyMethod = r.value.method;
            }
            else {
                errors.push(`${entities[i]}: ${this._asMessage(r.reason)}`);
            }
        }
        this._identifyError = errors.length ? errors.join("\n") : "";
        this._identifyCount = this._identifyCount + 1;
        // If EVERY entity errored, the loop is just generating noise.
        // Stop it so the user can read the failure.
        if (errors.length === results.length && this._identifyTimer != null) {
            clearInterval(this._identifyTimer);
            this._identifyTimer = null;
        }
    }
    /** v1.10.9: toggle an entity in the identify set.
     *
     *  In 1-at-a-time mode (default): selecting an entity replaces the
     *  current selection, deselecting clears it. State is restored on
     *  every entity that drops out of the set.
     *
     *  In all-at-once mode: same as v1.10.7 — checkboxes accumulate.
     */
    _toggleIdentifyEntity(entityId) {
        const next = new Set(this._identifySelected);
        const wasSelected = next.has(entityId);
        if (this._identifyOneAtATime) {
            // Radio behaviour: clicking always switches to JUST this entity
            // (or deselects it if it's already the only active one).
            const dropped = Array.from(next).filter((e) => e !== entityId);
            for (const e of dropped)
                void this._restoreEntityState(e);
            if (wasSelected) {
                // User clicked the active entity → deselect entirely.
                void this._restoreEntityState(entityId);
                this._identifySelected = new Set();
            }
            else {
                // Capture state for the newly-selected entity BEFORE the first
                // fire so we know what to restore.
                this._captureEntityState(entityId);
                this._identifySelected = new Set([entityId]);
            }
        }
        else {
            // All-at-once: accumulate checkboxes.
            if (wasSelected) {
                next.delete(entityId);
                void this._restoreEntityState(entityId);
            }
            else {
                this._captureEntityState(entityId);
                next.add(entityId);
            }
            this._identifySelected = next;
        }
        // Start/stop the timer based on whether anything is selected.
        if (this._identifySelected.size > 0 && this._identifyTimer == null) {
            void this._fireIdentifyOnce();
            this._identifyTimer = setInterval(() => void this._fireIdentifyOnce(), 5000);
        }
        else if (this._identifySelected.size === 0 && this._identifyTimer != null) {
            clearInterval(this._identifyTimer);
            this._identifyTimer = null;
        }
    }
    /** v1.10.9: toggle "Fire all simultaneously" vs default 1-at-a-time. */
    _toggleIdentifyMode() {
        this._identifyOneAtATime = !this._identifyOneAtATime;
        if (this._identifyOneAtATime && this._identifySelected.size > 1) {
            // Switching back to single mode: keep the first selected entity,
            // restore the rest.
            const keep = Array.from(this._identifySelected)[0];
            const dropped = Array.from(this._identifySelected).slice(1);
            for (const e of dropped)
                void this._restoreEntityState(e);
            this._identifySelected = new Set([keep]);
        }
    }
    /** v1.10.9: capture an entity's current state + attributes so we can
     *  restore on Stop / Found it / uncheck. Important for STROBE
     *  fallback path (cheap lights without SUPPORT_FLASH) where the
     *  manual on/off pattern would otherwise leave the light at default
     *  brightness / color, breaking Circadian Lighting + auto-off
     *  automations.
     */
    _captureEntityState(entityId) {
        const st = this.hass?.states?.[entityId];
        if (!st)
            return;
        if (this._identifySnapshots.has(entityId))
            return; // don't overwrite
        this._identifySnapshots.set(entityId, {
            state: st.state,
            attrs: { ...st.attributes },
        });
    }
    /** v1.10.9: restore an entity's pre-identify state. Called from
     *  every stop path (uncheck, "Found it!", "Stop", modal close).
     *
     *  Light: restore on/off + brightness + color_temp + rgb_color.
     *  Switch/fan: restore on/off.
     *  media_player, siren, others: no-op (chimes auto-end).
     *
     *  Errors are swallowed — restore is best-effort; failing because
     *  the entity disappeared is fine.
     */
    async _restoreEntityState(entityId) {
        if (!this.hass)
            return;
        const snap = this._identifySnapshots.get(entityId);
        if (!snap)
            return;
        this._identifySnapshots.delete(entityId);
        const domain = entityId.split(".")[0];
        try {
            if (domain === "light") {
                if (snap.state === "off" || snap.state === "unavailable") {
                    await this.hass.connection.sendMessagePromise({
                        type: "call_service",
                        domain: "light",
                        service: "turn_off",
                        target: { entity_id: entityId },
                    });
                }
                else {
                    // Restore on with whatever colour / brightness was set before.
                    // Skip null/undefined attrs so HA uses the entity's last known
                    // values rather than rejecting the call.
                    const restoreAttrs = {};
                    for (const key of [
                        "brightness",
                        "color_temp",
                        "color_temp_kelvin",
                        "rgb_color",
                        "rgbw_color",
                        "rgbww_color",
                        "hs_color",
                        "xy_color",
                        "effect",
                    ]) {
                        const v = snap.attrs[key];
                        if (v !== undefined && v !== null)
                            restoreAttrs[key] = v;
                    }
                    await this.hass.connection.sendMessagePromise({
                        type: "call_service",
                        domain: "light",
                        service: "turn_on",
                        target: { entity_id: entityId },
                        service_data: restoreAttrs,
                    });
                }
            }
            else if (domain === "switch" || domain === "fan" || domain === "input_boolean") {
                const service = snap.state === "on" ? "turn_on" : "turn_off";
                await this.hass.connection.sendMessagePromise({
                    type: "call_service",
                    domain,
                    service,
                    target: { entity_id: entityId },
                });
            }
            // media_player / siren / other: nothing to restore (chime auto-ends).
        }
        catch {
            // best-effort; if entity is gone, no-op.
        }
    }
    /** Close the identify modal and clear the recurring timer. Called by
     *  both "Found it!" and "Stop" — only difference is the toast text.
     *
     *  v1.10.9: also restore every captured entity to its pre-identify
     *  state. Avoids leaving the light ON at default brightness after
     *  the strobe fallback path, plus avoids stomping Circadian /
     *  auto-off automations. */
    async _stopIdentify(found) {
        if (this._identifyTimer != null) {
            clearInterval(this._identifyTimer);
            this._identifyTimer = null;
        }
        const entityCount = this._identifySelected.size;
        // Restore state for every entity that has a snapshot. Use the
        // snapshot map (not _identifySelected) so we restore EVERY entity
        // we ever fired on during this session, not just the currently-
        // selected ones (which could be a subset after the user unchecked
        // some during the session).
        const restorePromises = [];
        for (const entityId of Array.from(this._identifySnapshots.keys())) {
            restorePromises.push(this._restoreEntityState(entityId));
        }
        await Promise.allSettled(restorePromises);
        this._identifyOpen = false;
        this._identifyEntityId = "";
        this._identifySelected = new Set();
        this._identifyMethod = "";
        this._identifyError = "";
        this._identifyCount = 0;
        if (found && entityCount > 0) {
            this._toast = entityCount === 1
                ? `✅ Found it!`
                : `✅ Identification stopped (${entityCount} entities were active).`;
        }
    }
    /** v1.10.6: open the BLE live-find modal scoped to ONE entity.
     *  Checks BLE capability first; if the entity is trackable, opens
     *  the modal + subscribes to the per-scanner RSSI stream. */
    async _openBleFindForInsight(insight) {
        if (!this.hass)
            return;
        const entityId = this._primaryEntityId(insight);
        if (entityId === null) {
            this._failModal("No entity_id on this insight.");
            return;
        }
        try {
            const cap = await this.hass.connection.sendMessagePromise({
                type: "home_insights/ble_capability",
                entity_ids: [entityId],
            });
            const info = cap.capabilities?.[entityId];
            if (!info || !info.is_trackable || !info.bluetooth_address) {
                this._failModal(`BLE find not available for ${entityId}: ${info?.reason ?? "no capability info"}`);
                return;
            }
            this._bleFindEntity = entityId;
            this._bleFindAddress = info.bluetooth_address;
            this._bleFindLatest = null;
            this._bleTrendBuffer = [];
            this._bleFindError = "";
            this._bleFindOpen = true;
            void this._subscribeBleFind();
        }
        catch (err) {
            this._failModal(`BLE capability check failed: ${this._asMessage(err)}`);
        }
    }
    async _subscribeBleFind() {
        if (!this.hass)
            return;
        if (this._bleFindUnsub != null) {
            this._bleFindUnsub();
            this._bleFindUnsub = null;
        }
        try {
            this._bleFindUnsub =
                await this.hass.connection.subscribeMessage((event) => {
                    this._bleFindLatest = { ...event, received_at: Date.now() };
                    const next = [...this._bleTrendBuffer, event.rssi_smoothed];
                    if (next.length > 8)
                        next.shift();
                    this._bleTrendBuffer = next;
                }, {
                    type: "home_insights/ble_live_find",
                    bluetooth_address: this._bleFindAddress,
                });
        }
        catch (err) {
            this._bleFindError = this._asMessage(err);
        }
    }
    _closeBleFind() {
        if (this._bleFindUnsub != null) {
            this._bleFindUnsub();
            this._bleFindUnsub = null;
        }
        this._bleFindOpen = false;
        this._bleFindLatest = null;
        this._bleTrendBuffer = [];
        this._bleFindError = "";
    }
    _bleTrend() {
        const buf = this._bleTrendBuffer;
        if (buf.length < 4)
            return { arrow: "·", label: "settling" };
        const recent = (buf[buf.length - 1] + buf[buf.length - 2]) / 2;
        const earlier = (buf[buf.length - 4] + buf[buf.length - 3]) / 2;
        const delta = recent - earlier;
        if (delta > 2)
            return { arrow: "↑", label: "getting closer" };
        if (delta < -2)
            return { arrow: "↓", label: "getting further" };
        return { arrow: "→", label: "stable" };
    }
    _rssiBucket(rssi) {
        if (rssi >= -55)
            return { label: "HOT", color: "#ef4444" };
        if (rssi >= -70)
            return { label: "warm", color: "#f97316" };
        if (rssi >= -85)
            return { label: "cool", color: "#3b82f6" };
        return { label: "cold", color: "#6b7280" };
    }
    /** v1.10.7: render the looping-identify modal. Pre-v1.10.7 a single
     *  call fired with a toast outside the dialog; users couldn't catch
     *  the flash and the toast disappeared. New flow: a focused modal
     *  with a checkbox list of every referenced entity, a fire counter,
     *  and "Found it!" / "Stop" buttons. The recurring timer fires every
     *  5 seconds until the user closes or unchecks all entities. */
    _renderIdentifyModal() {
        if (!this._identifyOpen)
            return A;
        const selectedCount = this._identifySelected.size;
        const totalCount = this._identifyAllEntities.length;
        const singleEntity = totalCount === 1;
        return b `
      <div class="dialog-backdrop" @click=${() => this._stopIdentify(false)}>
        <div
          class="dialog identify-dialog"
          @click=${(e) => e.stopPropagation()}
        >
          <div class="dialog-header">
            <div class="dialog-title">
              🔆 Identifying ${singleEntity ? this._identifyAllEntities[0] : `${selectedCount} of ${totalCount} entities`}
            </div>
            <button
              class="dialog-close"
              aria-label="Close"
              @click=${() => this._stopIdentify(false)}
            >×</button>
          </div>
          <div class="dialog-body">
            <div class="identify-status">
              <div class="identify-counter">Fired ${this._identifyCount} ${this._identifyCount === 1 ? "time" : "times"}</div>
              ${this._identifyMethod
            ? b `<div class="identify-method">method: ${this._identifyMethod}</div>`
            : ""}
              ${this._identifyError
            ? b `<div class="identify-error">${this._identifyError}</div>`
            : ""}
            </div>
            ${totalCount > 1
            ? b `
                  <div class="identify-hint">
                    ${this._identifyOneAtATime
                ? b `
                          <strong>Click a row to start identifying it.</strong>
                          Click again (or another row) to switch. Restored
                          to pre-identify state on stop — so Circadian
                          Lighting and auto-off automations don't kick in
                          mid-search.
                        `
                : b `
                          <strong>All-at-once mode:</strong> tick rows to
                          add them, untick to drop. State is restored on
                          every drop.
                        `}
                  </div>
                  <label class="identify-mode-toggle">
                    <input
                      type="checkbox"
                      ?checked=${!this._identifyOneAtATime}
                      @change=${() => this._toggleIdentifyMode()}
                    />
                    <span>Fire all simultaneously (advanced)</span>
                  </label>
                  <div class="identify-entity-list">
                    ${this._identifyAllEntities.map((eid) => {
                const active = this._identifySelected.has(eid);
                const inputType = this._identifyOneAtATime
                    ? "radio"
                    : "checkbox";
                return b `
                        <label class="identify-entity-row ${active ? "active" : ""}">
                          <input
                            type="${inputType}"
                            name="identify-target"
                            ?checked=${active}
                            @change=${() => this._toggleIdentifyEntity(eid)}
                          />
                          <span>${eid}</span>
                        </label>
                      `;
            })}
                  </div>
                `
            : b `
                  <div class="identify-hint">
                    The identifier fires every 5 seconds — look or
                    listen for the flash / chime / beep. The entity's
                    pre-identify state (brightness / color / on-off) is
                    restored when you click "Found it!" or "Stop".
                  </div>
                `}
          </div>
          <div class="dialog-footer">
            <button
              class="action primary"
              @click=${() => this._stopIdentify(true)}
            >
              ✅ Found it!
            </button>
            <button
              class="action"
              @click=${() => this._stopIdentify(false)}
            >
              Stop
            </button>
          </div>
        </div>
      </div>
    `;
    }
    /** v1.10.6: render the BLE find modal — latest RSSI + trend arrow.
     *
     *  The strategy is the same as the bulk-area-assign BLE modal but
     *  scoped to a single entity (passed by the user clicking 📡 in the
     *  insight detail-dialog). Shows:
     *    - Big RSSI number with color bucket (HOT/warm/cool/cold)
     *    - Trend arrow (↑↓→) telling user which direction signal is
     *      moving — wave the phone around to find the device
     *    - Last scanner that saw it (helps in multi-proxy setups)
     *
     *  Subscription auto-tears down on close. EXPERIMENTAL — only works
     *  for entities the BLE-capability endpoint says are trackable. */
    _renderBleFindModal() {
        if (!this._bleFindOpen)
            return A;
        const latest = this._bleFindLatest;
        const trend = this._bleTrend();
        const bucket = latest ? this._rssiBucket(latest.rssi_smoothed) : null;
        return b `
      <div class="dialog-backdrop" @click=${this._closeBleFind}>
        <div class="dialog ble-find-dialog" @click=${(e) => e.stopPropagation()}>
          <div class="dialog-header">
            <div class="dialog-title">📡 BLE find — ${this._bleFindEntity}</div>
            <button class="dialog-close" aria-label="Close" @click=${this._closeBleFind}>×</button>
          </div>
          <div class="dialog-body">
            ${this._bleFindError
            ? b `<div class="ble-error">${this._bleFindError}</div>`
            : ""}
            ${latest && bucket
            ? b `
                  <div class="ble-rssi-block" style="color: ${bucket.color};">
                    <div class="ble-rssi-num">${latest.rssi_smoothed.toFixed(0)} dBm</div>
                    <div class="ble-rssi-label">${bucket.label}</div>
                    <div class="ble-trend">${trend.arrow} ${trend.label}</div>
                    <div class="ble-scanner">last seen by: ${latest.scanner}</div>
                  </div>
                `
            : b `<div class="ble-rssi-block" style="color: var(--secondary-text-color);">
                  <div class="ble-rssi-num">— dBm</div>
                  <div class="ble-rssi-label">waiting…</div>
                </div>`}
            <p class="ble-hint">
              <strong>Room-level localization.</strong> Each row above
              is one of your stationary Bluetooth proxies — higher RSSI
              means the device is closer to that proxy. Best results
              with one proxy per room.
              <br /><br />
              <em>Note:</em> the trend arrow tracks per-advertisement
              RSSI fluctuation (noise from the device), NOT your
              movement. True "warmer/colder" UX requires a mobile
              scanner — pending an HA Companion app active-scan
              feature.
            </p>
          </div>
          <div class="dialog-footer">
            <button class="action" @click=${this._closeBleFind}>Stop &amp; close</button>
          </div>
        </div>
      </div>
    `;
    }
    async _explain(insight) {
        if (!this.hass)
            return;
        this._explainBusy = true;
        try {
            const result = await this.hass.connection.sendMessagePromise({
                type: "home_insights/explain",
                insight_id: insight.id,
            });
            this._insights = this._insights.map((i) => i.id === insight.id ? { ...i, explanation: result.explanation } : i);
        }
        catch (err) {
            this._failModal(`Explain failed: ${this._asMessage(err)}`);
        }
        finally {
            this._explainBusy = false;
        }
    }
    /** v0.9 phase 6: ask the LLM for plausible causes of an anomaly. */
    async _hypothesize(insight) {
        if (!this.hass)
            return;
        this._hypothesizeBusy = true;
        try {
            const result = await this.hass.connection.sendMessagePromise({
                type: "home_insights/hypothesize",
                insight_id: insight.id,
            });
            const next = new Map(this._hypothesisById);
            next.set(insight.id, result.hypothesis ?? "");
            this._hypothesisById = next;
        }
        catch (err) {
            this._failModal(`Hypothesize failed: ${this._asMessage(err)}`);
        }
        finally {
            this._hypothesizeBusy = false;
        }
    }
    async _refine(insight) {
        if (!this.hass)
            return;
        this._refineBusy = true;
        this._modalError = undefined;
        try {
            // v1.0 RC #1: pre-flight cost estimate. The server runs the same
            // redactor + prompt build as the actual Refine but stops before
            // the LLM call, so we get an accurate token + USD figure for free.
            // If it crosses the configured threshold, ask the user to confirm
            // before burning tokens. Failures fall through silently — we'd
            // rather Refine than block on a flaky pre-flight.
            const feedback = (this._feedbackById.get(insight.id) ?? "").trim();
            try {
                const estimate = await this.hass.connection.sendMessagePromise({
                    type: "home_insights/refine_cost_estimate",
                    insight_id: insight.id,
                    ...(feedback ? { feedback } : {}),
                });
                if (estimate.requires_confirm) {
                    const tokens = estimate.tokens_in + estimate.tokens_out;
                    const dollars = estimate.cost_usd.toFixed(4);
                    const agent = estimate.agent_id ?? "default agent";
                    const ok = window.confirm(`Refine on ${agent} will use ~${tokens} tokens (~$${dollars}). ` +
                        `That's above the configured $${estimate.threshold_usd.toFixed(2)} ` +
                        `threshold. Continue?`);
                    if (!ok) {
                        this._toast = "Refine canceled";
                        return;
                    }
                }
            }
            catch {
                // Pre-flight failed — proceed with the actual refine; the user
                // sees the regular refine error path if it really is broken.
            }
            const message = {
                type: "home_insights/refine",
                insight_id: insight.id,
            };
            if (feedback)
                message.feedback = feedback;
            // Thread the prior conversation_id (if any) so the agent retains
            // context across turns. Server failover automatically drops it
            // when falling over to a different agent.
            const prior = this._refineConversationById.get(insight.id);
            if (prior)
                message.conversation_id = prior;
            const result = await this.hass.connection.sendMessagePromise(message);
            // Capture the new (or echoed) conversation_id for the next turn.
            if (result.conversation_id) {
                const nextConv = new Map(this._refineConversationById);
                nextConv.set(insight.id, result.conversation_id);
                this._refineConversationById = nextConv;
            }
            const nextTurns = new Map(this._refineTurnsById);
            nextTurns.set(insight.id, (nextTurns.get(insight.id) ?? 0) + 1);
            this._refineTurnsById = nextTurns;
            const next = new Map(this._refinedById);
            next.set(insight.id, {
                payload: result.refined_payload,
                rationale: result.rationale,
                diffSummary: result.diff_summary,
            });
            this._refinedById = next;
            // Clear the feedback once the LLM has consumed it; the user can type
            // fresh notes for the next refine pass.
            const nextFb = new Map(this._feedbackById);
            nextFb.delete(insight.id);
            this._feedbackById = nextFb;
            this._toast = result.diff_summary.length > 0
                ? `Refined: ${result.diff_summary.length} change(s) proposed`
                : "Refined: no changes proposed";
        }
        catch (err) {
            const message = this._asMessage(err);
            // If validation rejected the refinement because the LLM added an
            // entity not in the original, auto-populate the feedback box with a
            // constraint hint so the user can click Refine again to retry. The
            // hint references the original payload's entity_ids only.
            const hint = this._buildConstraintHint(insight, message);
            if (hint) {
                const fb = new Map(this._feedbackById);
                fb.set(insight.id, hint);
                this._feedbackById = fb;
                this._failModal(`${message}\n\n→ A constraint hint has been added below. ` +
                    "Click ✨ Refine again to retry with that hint.");
            }
            else {
                this._failModal(`Refine failed: ${message}`);
            }
        }
        finally {
            this._refineBusy = false;
        }
    }
    async _previewRedaction(insight) {
        if (!this.hass)
            return;
        // Toggle off if already shown
        if (this._previewById.has(insight.id)) {
            const next = new Map(this._previewById);
            next.delete(insight.id);
            this._previewById = next;
            return;
        }
        this._previewBusy = true;
        try {
            const result = await this.hass.connection.sendMessagePromise({
                type: "home_insights/redaction_preview",
                insight_id: insight.id,
            });
            const next = new Map(this._previewById);
            next.set(insight.id, result);
            this._previewById = next;
        }
        catch (err) {
            this._failModal(`Preview failed: ${this._asMessage(err)}`);
        }
        finally {
            this._previewBusy = false;
        }
    }
    _renderPreview(insight) {
        const preview = this._previewById.get(insight.id);
        if (!preview)
            return A;
        const pseudonymCount = Object.keys(preview.pseudonym_map).length;
        return b `
      <div class="preview">
        <div class="preview-header">
          <strong>🛡️ What the LLM would see (${preview.privacy_mode} mode)</strong>
          <button
            class="dialog-close"
            aria-label="Close preview"
            @click=${() => this._previewRedaction(insight)}
          >×</button>
        </div>
        <div class="preview-stats">
          <span>${pseudonymCount} entit${pseudonymCount === 1 ? "y" : "ies"} pseudonymized</span>
          <span>${preview.attributes_stripped.length} attribute${preview.attributes_stripped.length === 1 ? "" : "s"} stripped</span>
          ${preview.entities_blocked.length > 0
            ? b `<span style="color: var(--error-color)">${preview.entities_blocked.length} blocked</span>`
            : A}
        </div>
        <pre>${JSON.stringify(preview.redacted_payload, null, 2)}</pre>
        ${pseudonymCount > 0
            ? b `
              <div class="preview-pseudonyms">
                Pseudonym map (kept locally only):
                ${Object.entries(preview.pseudonym_map).map(([real, pseudo]) => b `
                    <div>
                      <code>${real}</code> → <code>${pseudo}</code>
                    </div>
                  `)}
              </div>
            `
            : A}
      </div>
    `;
    }
    /**
     * Detect the "hallucinated entity" validation failure pattern and build
     * a constraint hint that names the legal entity_ids from the original
     * payload. Returns null for any other error so the user just sees the
     * raw refine_failed message.
     */
    _buildConstraintHint(insight, errorMessage) {
        if (!/references entities not in the original/i.test(errorMessage)) {
            return null;
        }
        const allowed = this._collectEntityIds(insight.payload);
        if (allowed.length === 0)
            return null;
        return (`Use ONLY these entity_ids: ${allowed.join(", ")}. `
            + "Do not introduce any new entities. "
            + "Adding new services (e.g. light.turn_off) on the existing "
            + "entities is fine.");
    }
    /**
     * Mirror of the server-side _collect_entity_ids: walk the payload and
     * gather entity_id values from `entity_id` / `entity_ids` fields only.
     */
    _collectEntityIds(value, inEntityField = false) {
        if (value == null)
            return [];
        if (typeof value === "string") {
            if (!inEntityField)
                return [];
            const matches = value.match(/\b[a-z_]+\.[a-z0-9_]+\b/g) ?? [];
            return matches;
        }
        if (Array.isArray(value)) {
            const out = [];
            for (const item of value) {
                out.push(...this._collectEntityIds(item, inEntityField));
            }
            return Array.from(new Set(out));
        }
        if (typeof value === "object") {
            const out = [];
            for (const [key, sub] of Object.entries(value)) {
                const nestedInEntityField = inEntityField || key === "entity_id" || key === "entity_ids";
                out.push(...this._collectEntityIds(sub, nestedInEntityField));
            }
            return Array.from(new Set(out));
        }
        return [];
    }
    _keepOriginal(insightId) {
        const next = new Map(this._refinedById);
        next.delete(insightId);
        this._refinedById = next;
        this._resetRefineConversation(insightId);
        this._toast = "Kept original";
    }
    /** v1.0 RC #2: clear the multi-turn refine context for an insight. */
    _resetRefineConversation(insightId) {
        if (this._refineConversationById.has(insightId)) {
            const next = new Map(this._refineConversationById);
            next.delete(insightId);
            this._refineConversationById = next;
        }
        if (this._refineTurnsById.has(insightId)) {
            const next = new Map(this._refineTurnsById);
            next.delete(insightId);
            this._refineTurnsById = next;
        }
    }
    async _testActions(insight, override) {
        if (!this.hass)
            return;
        const which = override ? "refined" : "original";
        this._testBusy = true;
        this._testResults = undefined;
        try {
            const payload = {
                type: "home_insights/test_actions",
                insight_id: insight.id,
            };
            if (override)
                payload.payload_override = override;
            const result = await this.hass.connection.sendMessagePromise(payload);
            this._testResults = {
                ran: result.ran,
                error_count: result.error_count,
                results: result.results,
                tested: which,
            };
        }
        catch (err) {
            this._failModal(`Test actions failed: ${this._asMessage(err)}`);
        }
        finally {
            this._testBusy = false;
        }
    }
    _clearTestResults() {
        this._testResults = undefined;
    }
    /** Heading for the payload view, based on payload_format.
     * Stops the modal from labelling a "report" or "blueprint" payload
     * as "Automation that would be created" — confusing for SetupQuality
     * tier rows and orphan_device anomalies that aren't applyable. */
    _payloadHeading(format) {
        switch (format) {
            case "automation":
                return "Automation that would be created";
            case "blueprint":
                return "Blueprint that would be created";
            case "card":
                return "Card that would be added";
            case "group":
                return "Group that would be created";
            case "scene":
                return "Scene that would be created";
            case "report":
            default:
                return "Details";
        }
    }
    _renderPayloadView(insight, basePayload) {
        const editing = this._editingPayloadFor.has(insight.id);
        const draft = this._payloadEditsById.get(insight.id);
        const parseError = this._payloadParseErrorById.get(insight.id);
        const rawView = basePayload ?? insight.payload;
        // v1.2.16: strip private detector metadata (underscore-prefixed
        // keys like _manual_habit, _audit) from the YAML preview so the
        // user sees what will actually be written to automations.yaml,
        // not an extra blob of "what does this even mean" detector
        // bookkeeping. The server-side writer (v1.5.34) strips the same
        // keys before write — this is the visual equivalent.
        const view = this._stripPrivateKeys(rawView);
        return b `
      <div class="payload-edit">
        <button
          @click=${() => this._togglePayloadEdit(insight, basePayload)}
          title=${editing
            ? "Discard edits and revert"
            : "Edit the payload as JSON before Apply"}
        >
          ${editing ? "✕ Cancel edit" : "✎ Edit"}
        </button>
      </div>
      ${editing
            ? b `
            <textarea
              class="payload-editor ${parseError ? "error" : ""}"
              spellcheck="false"
              .value=${draft ?? JSON.stringify(view, null, 2)}
              @input=${(e) => this._onPayloadEditInput(insight.id, e)}
            ></textarea>
            ${parseError
                ? b `<div class="payload-error">${parseError}</div>`
                : A}
          `
            : b `<pre>${JSON.stringify(view, null, 2)}</pre>`}
    `;
    }
    /** v1.2.16 — drop top-level keys prefixed with `_` from the YAML
     *  preview. Detectors stash internal metadata under `_manual_habit`,
     *  `_audit`, `_streak`, etc. — useful for cohort dedup + fingerprinting
     *  but invisible to the user when they open automations.yaml.
     *  Returns a shallow copy; caller's object is untouched.
     *
     *  v1.2.20: keep `_*_assessment` keys visible. Those carry the
     *  v1.5.35+ grader output (timing / cooccurrence / persistence) and
     *  are the transparency layer users need to understand WHY their
     *  confidence is what it is. The server-side automation_writer
     *  (v1.5.34) strips them before write, so they never reach
     *  automations.yaml regardless of what's in the preview.
     */
    _stripPrivateKeys(payload) {
        if (!payload || typeof payload !== "object")
            return {};
        const out = {};
        for (const [k, v] of Object.entries(payload)) {
            if (!k.startsWith("_") || k.endsWith("_assessment")) {
                out[k] = v;
            }
        }
        return out;
    }
    _renderModalError() {
        if (!this._modalError)
            return A;
        return b `
      <div class="error-banner" style="margin-bottom: 12px; border-radius: 6px;">
        <span>${this._modalError}</span>
        <button @click=${() => (this._modalError = undefined)}>Dismiss</button>
      </div>
    `;
    }
    _renderTestResults() {
        const tr = this._testResults;
        if (!tr)
            return A;
        const allOk = tr.error_count === 0 && tr.ran > 0;
        const allFail = tr.ran === 0 && tr.error_count > 0;
        const cls = allOk ? "test-results ok" : allFail ? "test-results fail" : "test-results";
        const summary = `Tested ${tr.tested} — ${tr.ran} ran, ${tr.error_count} error${tr.error_count === 1 ? "" : "s"}`;
        return b `
      <div class=${cls}>
        <div class="test-results-header">
          <span>${summary}</span>
          <button
            class="test-results-close"
            aria-label="Close test results"
            @click=${this._clearTestResults}
          >×</button>
        </div>
        <ul>
          ${tr.results.map((r) => {
            const icon = r.ok ? "✓" : r.skipped ? "—" : "✗";
            const iconCls = r.ok ? "icon-ok" : r.skipped ? "icon-skip" : "icon-fail";
            return b `
              <li>
                <span class="icon ${iconCls}">${icon}</span>
                <div>
                  <div>
                    ${r.service ?? "(action)"}${r.skipped ? " (skipped)" : ""}
                  </div>
                  ${r.error
                ? b `<div class="test-results-error">${r.error}</div>`
                : A}
                </div>
              </li>
            `;
        })}
        </ul>
      </div>
    `;
    }
    /** Auto-pick a tts.* entity if the user didn't configure one. */
    _resolveTtsEngine() {
        if (this._config.tts_engine_entity_id)
            return this._config.tts_engine_entity_id;
        const states = this.hass?.states ?? {};
        return Object.keys(states).find((eid) => eid.startsWith("tts."));
    }
    async _readAloud(insight) {
        if (!this.hass || !insight.explanation)
            return;
        const target = this._config.tts_target_entity_id;
        if (!target)
            return;
        const engine = this._resolveTtsEngine();
        if (!engine) {
            this._failModal("No TTS engine found. Install one (Piper / Google Cloud / Nabu Casa) or set " +
                "tts_engine_entity_id in the card config.");
            return;
        }
        this._ttsBusy = true;
        try {
            await this.hass.connection.sendMessagePromise({
                type: "call_service",
                domain: "tts",
                service: "speak",
                service_data: {
                    entity_id: engine,
                    media_player_entity_id: target,
                    message: insight.explanation,
                },
            });
            this._toast = `Speaking on ${target}`;
        }
        catch (err) {
            this._failModal(`TTS failed: ${this._asMessage(err)}`);
        }
        finally {
            this._ttsBusy = false;
        }
    }
    _asMessage(err) {
        if (err && typeof err === "object" && "message" in err) {
            return String(err.message);
        }
        return String(err);
    }
    _filtered() {
        const min = this._config.min_confidence ?? 0;
        const userMax = this._config.max_rows;
        const cap = userMax !== undefined
            ? userMax
            : this._autoMaxRows > 0
                ? this._autoMaxRows
                : DEFAULT_MAX_ROWS;
        const search = (this._config.search ?? "").trim().toLowerCase();
        const sortBy = this._config.sort_by ?? "confidence";
        // v1.1 panel-only chip filters. Empty array OR undefined = no filter
        // for that dimension. Empty value (`null` device_class, `null` area)
        // passes only if the corresponding filter list is empty.
        const domainSet = new Set(this._config.domain_filter ?? []);
        const areaSet = new Set(this._config.area_filter ?? []);
        const dcSet = new Set(this._config.device_class_filter ?? []);
        const detSet = new Set(this._config.detector_filter ?? []);
        const floorSet = new Set(this._config.floor_filter ?? []);
        const integSet = new Set(this._config.integration_filter ?? []);
        const labelSet = new Set(this._config.label_filter ?? []);
        const hideAlreadyAutomated = this._config.hide_already_automated === true;
        const filtered = this._insights
            .filter((i) => i.confidence >= min)
            .filter((i) => !search || i.title.toLowerCase().includes(search))
            .filter((i) => domainSet.size === 0 || (i.domain != null && domainSet.has(i.domain)))
            .filter((i) => areaSet.size === 0 || (i.area_id != null && areaSet.has(i.area_id)))
            .filter((i) => dcSet.size === 0 ||
            (i.device_class != null && dcSet.has(i.device_class)))
            .filter((i) => detSet.size === 0 || detSet.has(i.detector))
            .filter((i) => floorSet.size === 0 || (i.floor_id != null && floorSet.has(i.floor_id)))
            .filter((i) => integSet.size === 0 ||
            (i.integration != null && integSet.has(i.integration)))
            .filter((i) => labelSet.size === 0 ||
            (Array.isArray(i.labels) && i.labels.some((l) => labelSet.has(l))))
            .filter((i) => !hideAlreadyAutomated || i.conflicts_with.length === 0);
        filtered.sort((a, b) => {
            if (sortBy === "age") {
                // Newest first
                return (new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
            }
            if (sortBy === "detector") {
                const cmp = a.detector.localeCompare(b.detector);
                return cmp !== 0 ? cmp : b.confidence - a.confidence;
            }
            // Default: confidence (high first)
            return b.confidence - a.confidence;
        });
        // Client-side dedup pass. Works on whatever the server sent —
        // useful when the server hasn't been reloaded since the dedup
        // helper shipped, or when the store has insights from an older
        // fingerprint schema. Pure presentation transform; no WS calls.
        const deduped = this._clientSideDedup(filtered);
        // Stash the full match count so the compact tile and "Showing X
        // of Y" footer can report the TRUE count instead of the
        // post-cap subset. Was previously hard-pinned to whatever
        // max_rows said, which made the dashboard's compact tile show
        // "1 insight" even when the user had 15 to look at.
        this._totalFilteredCount = deduped.length;
        return deduped.slice(0, cap);
    }
    /** Group insights by (detector, normalized title). Rows that share a
     *  normalized title AND a common domain get merged: highest-confidence
     *  one becomes the representative, others collapse into cohort_members.
     *  Idempotent — if the server already merged them (cohort_label set on
     *  every row of the bucket), pass through unchanged. */
    _clientSideDedup(rows) {
        if (rows.length < 2)
            return rows;
        const buckets = new Map();
        for (const r of rows) {
            // Strip entity_id-shaped tokens from the title to find similar rows.
            const norm = (r.title || "").replace(/\b[a-z_]+\.[A-Za-z0-9_]+\b/g, "<E>");
            // Include the row's domain in the bucket key so mixed-domain
            // titles never lump together. Without this split, an NVR with 35
            // binary_sensor offline rows + 11 switch offline rows all
            // bucketed into one mixed-domain bucket and then bailed out at
            // the "Mixed domains — keep separate" branch below, leaving the
            // user with 46 individual rows instead of 2 cohort representatives.
            const domain = r.domain ?? "";
            const key = `${r.detector}|${r.kind}|${norm}|${domain}`;
            const arr = buckets.get(key);
            if (arr)
                arr.push(r);
            else
                buckets.set(key, [r]);
        }
        const out = [];
        for (const bucket of buckets.values()) {
            if (bucket.length < 2) {
                out.push(bucket[0]);
                continue;
            }
            // Collect all entity_ids referenced by the bucket.
            const allEids = new Set();
            for (const ins of bucket) {
                const fp = ins.fingerprint;
                if (fp) {
                    for (const k of [
                        "entity_id",
                        "leader_entity_id",
                        "follower_entity_id",
                        "target_entity_id",
                    ]) {
                        const v = fp[k];
                        if (typeof v === "string" && v.includes("."))
                            allEids.add(v);
                    }
                }
                // Also pick up cohort_members from server-side merges so a
                // partially-merged bucket folds together cleanly.
                for (const m of ins.cohort_members ?? []) {
                    if (typeof m === "string" && m.includes("."))
                        allEids.add(m);
                }
            }
            const eidList = Array.from(allEids).sort();
            if (eidList.length < 2) {
                out.push(...bucket);
                continue;
            }
            const domains = new Set(eidList.map((e) => e.split(".", 1)[0]).filter(Boolean));
            let label;
            if (domains.size === 1) {
                const prefix = this._longestCommonPrefix(eidList);
                label = prefix ?? `${[...domains][0]}.* (cohort)`;
            }
            else {
                // Mixed domains — unusual but possible. Keep separate.
                out.push(...bucket);
                continue;
            }
            const rep = bucket.reduce((best, x) => (x.confidence ?? 0) > (best.confidence ?? 0) ? x : best);
            const others = bucket.length - 1;
            // Idempotent: if the server already added the suffix, don't double.
            const baseTitle = (rep.title || "").replace(/ \(\+\d+ similar entities[^)]*\)$/, "");
            const merged = {
                ...rep,
                title: `${baseTitle} (+${others} similar entities: ${label})`,
                cohort_members: eidList,
                cohort_label: label,
            };
            out.push(merged);
        }
        // Preserve sort order: re-sort by the original sortBy criterion.
        out.sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0));
        return out;
    }
    _longestCommonPrefix(eids) {
        if (eids.length < 2)
            return null;
        const domain = eids[0].split(".", 1)[0];
        const names = eids.map((e) => e.split(".", 2)[1] ?? "");
        let prefix = names[0];
        for (const n of names.slice(1)) {
            while (prefix && !n.startsWith(prefix))
                prefix = prefix.slice(0, -1);
            if (!prefix)
                return null;
        }
        prefix = prefix.replace(/_+$/, "");
        if (prefix.length < 4)
            return null;
        return `${domain}.${prefix}_*`;
    }
    /** Bucket insights by the configured group_by key. Returns ordered
     *  pairs so the render can produce stable section ordering. */
    _grouped(rows) {
        const key = this._config.group_by ?? "none";
        if (key === "none")
            return [["", rows]];
        const buckets = new Map();
        for (const row of rows) {
            // Prefer the friendly name when one is available — the area_id /
            // floor_id are opaque GUIDs in the registry, useless as section
            // headers. integration is already a label-ish string ("hue",
            // "tuya", "mqtt"). Fall back to "(no area)" / "(no floor)" /
            // "(no integration)" so a single bucket collects un-tagged rows
            // and the user can spot what slipped through the registry.
            const groupKey = key === "area"
                ? row.area_name ?? row.area_id ?? "(no area)"
                : key === "floor"
                    ? row.floor_name ?? row.floor_id ?? "(no floor)"
                    : key === "integration"
                        ? row.integration ?? "(no integration)"
                        : key === "label"
                            ? (Array.isArray(row.labels) && row.labels.length > 0
                                ? row.labels[0]
                                : "(no label)")
                            : key === "detector"
                                ? row.detector
                                : "";
            const existing = buckets.get(groupKey);
            if (existing)
                existing.push(row);
            else
                buckets.set(groupKey, [row]);
        }
        return Array.from(buckets.entries()).sort((a, b) => a[0].localeCompare(b[0]));
    }
    _openDialog(insightId) {
        this._dialogId = insightId;
        this._testResults = undefined;
        this._modalError = undefined;
    }
    _closeDialog() {
        if (this._dialogId) {
            // Discard rename + payload edits when the modal closes without applying.
            const id = this._dialogId;
            const renames = new Map(this._renameEdits);
            renames.delete(id);
            this._renameEdits = renames;
            const drafts = new Map(this._payloadEditsById);
            drafts.delete(id);
            this._payloadEditsById = drafts;
            const editing = new Set(this._editingPayloadFor);
            editing.delete(id);
            this._editingPayloadFor = editing;
            const errs = new Map(this._payloadParseErrorById);
            errs.delete(id);
            this._payloadParseErrorById = errs;
        }
        this._dialogId = undefined;
        this._testResults = undefined;
        this._modalError = undefined;
    }
    _renderModeBadge(mode) {
        if (!mode)
            return A;
        const cls = `badge badge-${mode}`;
        const label = mode === "off"
            ? "🚫 Off"
            : mode === "local"
                ? "🟢 Local"
                : "🟡 Cloud";
        return b `<span class=${cls} title="Privacy mode: ${mode}">${label}</span>`;
    }
    _renderHeader() {
        const title = this._config.title ?? "HA Insights";
        // v1.2.25: subtitle now describes STATE, not the version. Use the
        // total filtered count (already stashed by _filtered() before
        // truncation). Falls back to "Connecting…" while the hello
        // handshake is in flight. Protocol/version moves to the title's
        // tooltip so it stays available for debug without burning chrome.
        const count = this._totalFilteredCount;
        const sub = this._hello
            ? `${count} ${count === 1 ? "insight" : "insights"}`
            : "Connecting…";
        const versionTooltip = this._hello
            ? `${title} · v${this._hello.integration_version} · WS protocol ${this._hello.ws_protocol_version}`
            : title;
        return b `
      <div class="header">
        <div class="titles">
          <div class="title" title=${versionTooltip}>
            ${title} ${this._renderModeBadge(this._hello?.privacy_mode)}
          </div>
          <div class="subtitle">${sub}</div>
        </div>
        <button
          class="history-toggle ${this._showHistory ? "history-toggle-on" : ""}"
          title=${this._showHistory
            ? "Hide retired / dismissed / snoozed insights"
            : "Show retired / dismissed / snoozed insights"}
          aria-pressed=${this._showHistory ? "true" : "false"}
          @click=${this._toggleHistory}
        >
          ${this._showHistory ? "📚 Active only" : "📚 History"}
        </button>
        <a
          class="view-all"
          href="/ha-insights"
          title="Open the full HA Insights panel"
        >View all
          <ha-icon icon="mdi:arrow-right"></ha-icon>
        </a>
      </div>
    `;
    }
    _renderCompactTile(_rows) {
        // Report the FULL filter-matching count, not the cap-clipped one.
        // _filtered() stashes this for us before slicing.
        const count = this._totalFilteredCount;
        const label = count === 0
            ? "No insights yet — patterns will appear as your home settles in"
            : count === 1
                ? "1 insight ready to review"
                : `${count} insights ready to review`;
        return b `
      <a class="compact-tile" href="/ha-insights">
        <div>
          <div class="count">${count} ${count === 1 ? "insight" : "insights"}</div>
          <div class="label">${label}</div>
        </div>
        <div class="arrow">→</div>
      </a>
    `;
    }
    _renderSkewBanner() {
        if (!this._hello)
            return A;
        if (this._hello.ws_protocol_version === CARD_PROTOCOL_VERSION)
            return A;
        return b `
      <div class="skew-banner">
        Protocol mismatch — card expects v${CARD_PROTOCOL_VERSION}, integration is
        v${this._hello.ws_protocol_version}. Update one or the other.
      </div>
    `;
    }
    /** v1.5.13 — Render cohort dropdown rows with per-member 🔌 integration
     *  and 🏷️ external-app badges. Falls back to plain entity_id chips
     *  when the WS payload predates the cohort_member_info field. */
    _renderCohortMembers(insight, members) {
        const info = insight.cohort_member_info;
        if (!Array.isArray(info) || info.length === 0) {
            // Legacy / pre-v1.5.13 path — just the entity_id chip.
            return members.map((m) => b `<span class="cohort-member-chip">${m}</span>`);
        }
        // Build a lookup so we render members in the order of `cohort_members`
        // (canonical sort) but enriched with the metadata.
        const byId = new Map();
        for (const m of info) {
            byId.set(m.entity_id, {
                integration: m.integration,
                external_source: m.external_source,
            });
        }
        return members.map((eid) => {
            const meta = byId.get(eid);
            return b `<span class="cohort-member-chip">
        <span class="cohort-member-id">${eid}</span>
        ${meta?.integration
                ? b `<span
              class="cohort-member-badge cohort-member-int"
              title="Source integration"
            >🔌 ${meta.integration}</span>`
                : A}
        ${meta?.external_source
                ? b `<span
              class="cohort-member-badge cohort-member-ext"
              title="Schedule likely lives in ${meta.external_source}, not HA"
            >🏷️ ${meta.external_source}</span>`
                : A}
      </span>`;
        });
    }
    _renderRow(insight) {
        const confidencePct = Math.round(insight.confidence * 100);
        const confidenceClass = this._confidenceClass(insight.confidence);
        const ageLabel = this._formatAge(insight.created_at);
        const expanded = this._expandedCohorts.has(insight.id);
        const members = insight.cohort_members ?? [];
        const hasCohort = members.length > 0;
        // Audit-specific finding list: pulled from payload.observations
        // (set by the AutomationAuditDetector). Rendered as a collapsible
        // findings panel beneath the title row so the user sees the
        // observations at a glance.
        const auditObservations = this._auditObservationsFor(insight);
        const auditFixSummaries = this._auditFixSummariesFor(insight);
        const auditExpanded = this._expandedCohorts.has(`audit:${insight.id}`);
        return b `
      <div class="row" @click=${() => this._openDialog(insight.id)}>
        <div class="row-title">
          ${this._displayTitle(insight)}
          ${this._renderCouplingBadge(insight)}
          ${this._renderDirectionalityBadge(insight)}
          ${this._renderEntityAgeBadge(insight)}
          ${hasCohort
            ? b ` <button
                class="pill-action"
                style="margin-left:6px;"
                aria-label="${expanded ? "Hide" : "Show"} ${members.length} cohort members"
                aria-expanded="${expanded}"
                title="${expanded ? "Hide" : "Show"} the ${members.length} cohort members"
                @click=${(e) => {
                e.stopPropagation();
                this._toggleCohortExpansion(insight.id);
            }}
              >${expanded ? "▾ hide" : `▸ show ${members.length}`}</button>`
            : A}
          ${auditObservations.length > 0
            ? b ` <button
                class="pill-action"
                style="margin-left:6px;"
                aria-label="${auditExpanded ? 'Hide' : 'Show'} ${auditObservations.length} audit finding${auditObservations.length === 1 ? '' : 's'}"
                aria-expanded="${auditExpanded}"
                title="${auditExpanded ? 'Hide' : 'Show'} the ${auditObservations.length} audit finding${auditObservations.length === 1 ? '' : 's'}"
                @click=${(e) => {
                e.stopPropagation();
                this._toggleCohortExpansion(`audit:${insight.id}`);
            }}
              >${auditExpanded
                ? '▾ hide findings'
                : `▸ ${auditObservations.length} finding${auditObservations.length === 1 ? '' : 's'}`}</button>`
            : A}
        </div>
        ${auditObservations.length > 0 && auditExpanded
            ? b `<div
              class="audit-findings"
              @click=${(e) => e.stopPropagation()}
            >
              <ul>
                ${auditObservations.map((o) => b `<li title="${o.kind}">${o.text}</li>`)}
              </ul>
              ${auditFixSummaries.length > 0
                ? b `<div class="audit-fixes">
                    <strong>🔧 Auto-fix preview:</strong>
                    <ul>
                      ${auditFixSummaries.map((s) => b `<li>${s}</li>`)}
                    </ul>
                  </div>`
                : A}
            </div>`
            : A}
        ${hasCohort && expanded
            ? b `<div
              class="cohort-members"
              @click=${(e) => e.stopPropagation()}
            >${this._renderCohortMembers(insight, members)}</div>`
            : A}
        <div
          class="row-meta-primary"
          @click=${(e) => e.stopPropagation()}
          title="Click the title to open insight details — these badges show context only."
        >
          <span class="pill ${confidenceClass}">confidence ${confidencePct}%</span>
          ${this._renderMaturityPill(insight)}
          ${insight.applied_at
            ? b `<span
                class="pill"
                style="background: rgba(76, 175, 80, 0.18); color: var(--success-color, #2e7d32);"
                title="Applied at ${insight.applied_at}"
              >✓ applied</span>`
            : A}
          ${insight.conflicts_with.length > 0
            ? this._renderAutomationPill("🔁 already automated", "var(--warning-color)", "HA noticed this pattern, but you already have an automation that covers it", insight.conflicts_with_links ?? insight.conflicts_with.map((a) => ({ alias: a })))
            : A}
          ${insight.referenced_in_automations &&
            insight.referenced_in_automations.length > 0 &&
            insight.conflicts_with.length === 0
            ? this._renderAutomationPill(`🤖 in ${insight.referenced_in_automations.length} ${insight.referenced_in_automations.length === 1 ? "automation" : "automations"}`, "var(--secondary-text-color)", "The entities in this insight are referenced in your existing automation(s)", insight.referenced_in_automations_links ?? insight.referenced_in_automations.map((a) => ({ alias: a })))
            : A}
          ${this._renderTimingPill(insight)}
          ${insight.explanation
            ? b `<span class="pill" title="LLM explanation available">💬 explained</span>`
            : A}
          ${insight.detector === "automation_audit" && insight.payload_format === "report"
            ? b `<button
                class="pill-action"
                ?disabled=${this._auditSuggestBusy === insight.id}
                title="Ask the LLM for concrete YAML edits based on the audit findings"
                @click=${(e) => {
                e.stopPropagation();
                void this._runAuditSuggest(insight);
            }}
              >${this._auditSuggestBusy === insight.id ? "Thinking…" : "🤖 Suggest"}</button>`
            : A}
          ${insight.detector === "automation_audit" && insight.payload_format === "automation"
            ? b `<button
                class="pill-action"
                title="Preview the deterministic fix as a side-by-side diff (no LLM cost)"
                @click=${(e) => {
                e.stopPropagation();
                void this._previewDeterministicAudit(insight);
            }}
              >📋 Preview</button>`
            : A}
          ${insight.payload_format === "automation" && !insight.applied_at
            ? b `<button
                class="pill-action"
                ?disabled=${this._suggestAddBusy === insight.id}
                title="Find candidate entities to add to this automation's action block. Deterministic, no LLM tokens."
                @click=${(e) => {
                e.stopPropagation();
                void this._openSuggestAddDialog(insight);
            }}
              >${this._suggestAddBusy === insight.id ? "Loading…" : "💡 Add"}</button>`
            : A}
        </div>
        <div
          class="row-meta-secondary"
          @click=${(e) => e.stopPropagation()}
        >
          ${this._renderSecondaryMeta(insight, ageLabel)}
        </div>
      </div>
    `;
    }
    /** v1.2.25: tiered row meta — secondary line carries identity context
     *  (detector, area, integration, age, external source) as plain text
     *  separated by middle-dots. Trust pill dropped from rows because the
     *  card header already shows the privacy mode; per-row trust still
     *  surfaces in the insight modal where the header is hidden.
     */
    _renderSecondaryMeta(insight, ageLabel) {
        const parts = [insight.detector];
        if (insight.area_id) {
            parts.push(insight.area_name ?? insight.area_id);
        }
        if (insight.integration) {
            parts.push(insight.integration);
        }
        if (ageLabel) {
            parts.push(ageLabel);
        }
        if (insight.external_source) {
            parts.push(`managed by ${insight.external_source}`);
        }
        return b `${parts.map((part, i) => b `${i > 0 ? b `<span class="sep">·</span>` : A}${part}`)}`;
    }
    /** Pull the observations array off an audit insight's payload.
     *  Returns [] for non-audit insights. Tolerates payloads where
     *  `observations` is missing or malformed. */
    _auditObservationsFor(insight) {
        if (insight.detector !== "automation_audit")
            return [];
        const payload = insight.payload;
        if (!payload)
            return [];
        // Deterministic-fix audits stash observations under _audit.observations.
        const auditMeta = payload._audit;
        const raw = auditMeta?.observations ?? payload.observations;
        if (!Array.isArray(raw))
            return [];
        return raw
            .filter((o) => typeof o === "object" && o !== null)
            .map((o) => ({
            kind: typeof o.kind === "string" ? o.kind : "",
            text: typeof o.text === "string" ? o.text : "",
        }))
            .filter((o) => o.text.length > 0);
    }
    /** For deterministic-fix audit insights (payload_format = automation
     *  with _audit metadata), surface the human-readable summaries of
     *  what was changed. Empty list for the LLM-suggest path or reports. */
    _auditFixSummariesFor(insight) {
        if (insight.detector !== "automation_audit")
            return [];
        const payload = insight.payload;
        if (!payload)
            return [];
        const auditMeta = payload._audit;
        const raw = auditMeta?.fix_summaries;
        if (!Array.isArray(raw))
            return [];
        return raw.filter((s) => typeof s === "string");
    }
    _confidenceClass(confidence) {
        if (confidence >= 0.8)
            return "confidence-high";
        if (confidence >= 0.5)
            return "confidence-medium";
        return "confidence-low";
    }
    /** v1.2.17 — Surface the lib/timing_likelihood assessment as a small
     *  row pill so users see WHY a confidence is what it is.
     *
     *  Three tiers:
     *    DEVICE_LIKELY  → 🤖 device-managed pill, warning color. The
     *      timing is statistically too tight to be a human action (BLE
     *      toothbrush firing OFF exactly 2 min after ON, solar inverter
     *      at sunrise via cloud polling, etc). Confidence already cut
     *      by 80% server-side; the pill explains the demotion.
     *    TIGHT_PATTERN → 🤖 tight-pattern pill, info color. Plausibly
     *      human (alarm-driven routine) but tight enough that a device
     *      timer is also possible. Confidence cut by 15%; pill prompts
     *      the user to think about it.
     *    HUMAN_LIKELY / INSUFFICIENT_DATA → nothing rendered.
     *
     *  Backend ships `_timing_assessment` in the payload (underscore-
     *  prefixed → stripped before automations.yaml write). The card
     *  reads it for rendering only.
     */
    _renderTimingPill(insight) {
        const payload = insight.payload;
        if (!payload)
            return A;
        // v1.2.19: read all three grader assessments (the v1.5.38
        // composite payload-keys output). Any one signal alone produces a
        // pill; multiple signals stack into a multi-line tooltip.
        const t = payload._timing_assessment;
        const c = payload._cooccurrence_assessment;
        const p = payload._persistence_assessment;
        // v1.5.40: 4th grader — transition_entropy (context diversity).
        // Optional; present only when detector passed distinct_entity_counts.
        const e = payload._transition_entropy_assessment;
        const timingClass = typeof t?.timing_class === "string" ? t.timing_class : "";
        const cooccClass = typeof c?.cooccurrence_class === "string"
            ? c.cooccurrence_class
            : "";
        const persClass = typeof p?.persistence_class === "string"
            ? p.persistence_class
            : "";
        const entropyClass = typeof e?.transition_entropy_class === "string"
            ? e.transition_entropy_class
            : "";
        const isDeviceTiming = timingClass === "device_likely";
        const isTightTiming = timingClass === "tight_pattern";
        const isIsolatedCoocc = cooccClass === "isolated";
        const isAmbiguousCoocc = cooccClass === "ambiguous";
        const isFixedPersistence = persClass === "fixed_cycle";
        const isTightPersistence = persClass === "tight_duration";
        const isNovelEntropy = entropyClass === "novel_context";
        if (!isDeviceTiming
            && !isTightTiming
            && !isIsolatedCoocc
            && !isAmbiguousCoocc
            && !isFixedPersistence
            && !isTightPersistence
            && !isNovelEntropy) {
            return A;
        }
        // Multi-line tooltip — each signal contributes one paragraph so
        // the user sees the full evidence chain. Lit's title attribute
        // renders \n\n as a real line break in most browsers.
        const reasons = [];
        if (t?.reason && (isDeviceTiming || isTightTiming))
            reasons.push(t.reason);
        if (c?.reason && (isIsolatedCoocc || isAmbiguousCoocc))
            reasons.push(c.reason);
        if (p?.reason && (isFixedPersistence || isTightPersistence))
            reasons.push(p.reason);
        if (e?.reason && isNovelEntropy)
            reasons.push(e.reason);
        const reason = reasons.join("\n\n") || "Likelihood analysis details unavailable";
        // Severity escalation: any one strong device signal → "device-
        // managed" (warning color). Multiple soft signals stacking also
        // escalate. Otherwise tight-pattern (info color).
        const strongSignals = (isDeviceTiming ? 1 : 0)
            + (isIsolatedCoocc ? 1 : 0)
            + (isFixedPersistence ? 1 : 0);
        const softSignals = (isTightTiming ? 1 : 0)
            + (isAmbiguousCoocc ? 1 : 0)
            + (isTightPersistence ? 1 : 0)
            + (isNovelEntropy ? 1 : 0);
        const isDeviceManaged = strongSignals >= 1 || (strongSignals + softSignals) >= 3;
        if (isDeviceManaged) {
            return b `<span
        class="pill"
        style="color: var(--warning-color, #ef6c00); background: rgba(239, 108, 0, 0.08);"
        title=${reason}
      >🤖 device-managed</span>`;
        }
        return b `<span
      class="pill"
      style="color: var(--info-color, #2196f3); background: rgba(33, 150, 243, 0.08);"
      title=${reason}
    >🤖 tight-pattern</span>`;
    }
    /** Rewrite the title for already-shadowed insights so it doesn't read
     *  as a CTA. The detector emits "Pattern X. Automate this?" but when
     *  conflict_scanner has already matched an existing automation, that
     *  question is misleading — the answer is "no, you already did".
     *
     *  Server-side titles drive cohort-dedup grouping and notification
     *  payloads, so this transform is presentation-only. The 🔁 pill +
     *  conflicts_with_links still tell the full story.
     *
     *  Patterns stripped (case-insensitive trailing CTA):
     *    - "Automate this?" / "Automate it?" / "Automate it" / "Automate."
     *    - "Build automation?"
     *    - "Auto-off after N min?"  ← long_tail also reads as a CTA
     */
    _displayTitle(insight) {
        if (insight.conflicts_with.length === 0)
            return insight.title;
        return insight.title.replace(/\s*(?:Automate\s+(?:this|it)\??|Build\s+automation\??)\s*$/i, "").trim();
    }
    /** v1.4 (integration v1.9.1+): 🔀 directionality badge for
     *  lagged_correlation pairs.
     *
     *  The integration runs transfer entropy on every detected pair
     *  (`lib/transfer_entropy.py`) and stamps the result on the payload.
     *  We render three states, each with a distinct visual:
     *
     *  - **direction "x_to_y"** with non-trivial flow → ✅ "direction
     *    confirmed" (positive signal — the suggestion is well-grounded).
     *  - **direction "y_to_x"** with non-trivial flow → ⚠️ "direction
     *    looks reversed" (the proposed leader is actually the follower;
     *    the integration already demoted confidence ×0.5 so it usually
     *    falls below MIN_CONFIDENCE_TO_EMIT, but if one slipped through
     *    the user should know).
     *  - **direction "symmetric"** with both TEs above noise → 🔀
     *    "no clear direction" (both entities probably driven by a
     *    third factor like time of day, not by each other).
     *
     *  We skip rendering entirely when:
     *    - assessment wasn't run (`assessed: false`)
     *    - both TEs are below the noise floor (uninformative — usually
     *      sparse data; surfacing a badge would be misleading)
     *
     *  The integration is the source of truth for *what* to demote;
     *  the card is the source of truth for *how* to surface the
     *  rationale to the user. See `lib/transfer_entropy.py` and
     *  `detectors/lagged_correlation.py`.
     */
    _renderDirectionalityBadge(insight) {
        const payload = insight.payload ?? {};
        const dir = payload._directionality;
        if (!dir || dir.assessed !== true)
            return A;
        // Noise-floor cutoff matches NOISE_FLOOR_BITS in lib/transfer_entropy.py.
        // Mismatching this would surface badges the integration considered
        // uninformative — keep them in sync.
        const NOISE_FLOOR_BITS = 0.05;
        const txy = typeof dir.te_x_to_y === "number" ? dir.te_x_to_y : 0;
        const tyx = typeof dir.te_y_to_x === "number" ? dir.te_y_to_x : 0;
        if (txy < NOISE_FLOOR_BITS && tyx < NOISE_FLOOR_BITS)
            return A;
        let icon = "🔀";
        let label = "no clear direction";
        let tooltip = "";
        switch (dir.direction) {
            case "x_to_y":
                icon = "✅";
                label = "direction confirmed";
                tooltip = (`Transfer entropy ${txy.toFixed(2)} bits (forward) vs `
                    + `${tyx.toFixed(2)} bits (reverse) — the leader's past `
                    + "genuinely reduces uncertainty about the follower's future. "
                    + "This suggestion is well-grounded.");
                break;
            case "y_to_x":
                icon = "⚠️";
                label = "direction reversed";
                tooltip = (`Transfer entropy ${tyx.toFixed(2)} bits (reverse) vs `
                    + `${txy.toFixed(2)} bits (forward) — the proposed leader `
                    + "looks like the FOLLOWER. The entities may be mislabeled "
                    + "or the causation runs the other way. Inspect before applying.");
                break;
            case "symmetric":
                icon = "🔀";
                label = "no clear direction";
                tooltip = (`Forward and reverse transfer entropy are similar `
                    + `(${txy.toFixed(2)} vs ${tyx.toFixed(2)} bits) — both `
                    + "entities are probably driven by a third factor (time of "
                    + "day, a manual ritual, an unseen scene) rather than by "
                    + "each other. Consider whether automation adds value.");
                break;
            default:
                return A;
        }
        return b `<span
      class="pill-action directionality-badge"
      style="margin-left:6px;"
      role="img"
      aria-label="${tooltip}"
      title="${tooltip}"
    >${icon} ${label}</span>`;
    }
    /** v1.7: 🔗 badge for tight-coupled pairs.
     *
     *  Cooccurrence / lagged / button-press detectors stamp a `_coupling`
     *  block on the payload when the leader→follower lag looks like
     *  device-internal logic (ESPHome on_press, Z-Wave central scene,
     *  Zigbee binding) rather than a real user habit. We render the
     *  badge only for TIGHT tier — LOOSE is too ambiguous to surface,
     *  NONE is the normal case.
     *
     *  The integration also demotes confidence on TIGHT pairs so they
     *  rank below uncoupled suggestions; the badge tells the user
     *  WHY the insight is muted rather than hidden.
     */
    _renderCouplingBadge(insight) {
        const payload = insight.payload ?? {};
        const coupling = payload._coupling;
        if (!coupling || coupling.tier !== "TIGHT")
            return A;
        const lag = typeof coupling.median_lag_ms === "number"
            ? `${Math.round(coupling.median_lag_ms)}ms`
            : "<unknown>";
        const cons = typeof coupling.consistency === "number"
            ? `${Math.round(coupling.consistency * 100)}%`
            : "<unknown>";
        const tooltip = (`These entities change together within ~${lag} `
            + `(${cons} consistency) — looks like a device binding or a `
            + "pre-existing automation, not a new pattern to automate.");
        return b `<span
      class="pill-action coupling-badge"
      style="margin-left:6px;"
      role="img"
      aria-label="${tooltip}"
      title="${tooltip}"
    >🔗 coupled</span>`;
    }
    /** v1.12.11: 🆕 badge for insights whose primary entity was added to
     *  HA within the last NEWLY_ADDED_THRESHOLD_DAYS (14) days.
     *
     *  Surfaces the dataset-window limit so users know why a brand-new
     *  entity's insight may look noisy or hedged — there literally isn't
     *  enough history yet. Detectors like state_shift already gate
     *  internally; this badge is the visible explanation.
     *
     *  Server attaches `entity_age_days` only when within threshold, so
     *  absence == "not newly added" (or pre-HA-2024.10 registry without
     *  created_at, in which case we can't tell). Either way, no badge.
     */
    _renderEntityAgeBadge(insight) {
        const age = insight.entity_age_days;
        if (typeof age !== "number")
            return A;
        let label;
        if (age === 0)
            label = "added today";
        else if (age === 1)
            label = "added yesterday";
        else
            label = `added ${age} days ago`;
        const tooltip = (`This entity was ${label.replace("added ", "")} `
            + "in Home Assistant. Detectors have limited history to work "
            + "from, so any pattern, anomaly, or shift may not be reliable "
            + "yet — give it a couple of weeks before acting on it.");
        return b `<span
      class="pill-action entity-age-badge"
      style="margin-left:6px;"
      role="img"
      aria-label="${tooltip}"
      title="${tooltip}"
    >🆕 ${label}</span>`;
    }
    /** v1.7.7: render the "Managed devices" section in the detail dialog.
     *
     *  Lists every device this insight references with a toggle to mark
     *  it "managed externally" — a user assertion that the device handles
     *  its own logic and HA Insights should stop surfacing patterns from
     *  it. Companion to the 🔗 coupling badge: that one INFERS coupling
     *  from timing; this one is the explicit user override.
     *
     *  Shown only when the insight carries `referenced_devices` (server
     *  v1.7.7+) AND at least one device is present. Cohort insights with
     *  many member devices show all of them.
     *
     *  Toggling fires `home_insights/set_device_managed`. After the
     *  toggle, currently-emitted insights from the device stay in the
     *  store (they'll be cleaned up by the next scan's stale-sweep) but
     *  any future scan won't surface new patterns. We optimistically
     *  update the local insight's device.managed flag so the toggle
     *  reflects immediately.
     */
    _renderManagedDevicesSection(insight) {
        const devices = insight.referenced_devices;
        if (!devices || devices.length === 0)
            return A;
        return b `
      <h4>Devices</h4>
      <div class="managed-devices">
        <p style="margin-top:0; color: var(--secondary-text-color); font-size: 0.92em;">
          Mark a device "managed externally" to stop surfacing patterns
          from it. Different from automatic device-managed detection
          — this is your explicit assertion.
        </p>
        <ul style="list-style: none; padding: 0; margin: 0;">
          ${devices.map((d) => b `
            <li style="display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid var(--divider-color);">
              <span style="flex: 1;">
                <strong>${d.name}</strong>
                <span style="color: var(--secondary-text-color); font-size: 0.85em; margin-left: 6px;">${d.device_id.slice(0, 8)}…</span>
              </span>
              ${d.managed
            ? b `<button
                    class="pill-action"
                    style="background: var(--warning-color, #ef6c00); color: white; border-color: var(--warning-color, #ef6c00);"
                    title="Currently suppressed. Click to restore — future patterns from this device will surface again."
                    @click=${() => this._setDeviceManaged(d.device_id, false)}
                  >✓ Suppressed — restore</button>`
            : b `<button
                    class="pill-action"
                    title="Stop surfacing future insights from this device. Existing insights stay until next scan."
                    @click=${() => this._setDeviceManaged(d.device_id, true)}
                  >🔇 Suppress device</button>`}
            </li>
          `)}
        </ul>
      </div>
    `;
    }
    /** Toggle a device's managed-externally flag. Optimistic UI: flip
     *  the local insight's `referenced_devices[].managed` immediately,
     *  then call the server. On failure, log + leave the optimistic
     *  state (user can retry; next scan will re-sync). */
    async _setDeviceManaged(deviceId, managed) {
        // Optimistic local update
        this._insights = this._insights.map((i) => {
            if (!i.referenced_devices)
                return i;
            if (!i.referenced_devices.some((d) => d.device_id === deviceId))
                return i;
            return {
                ...i,
                referenced_devices: i.referenced_devices.map((d) => d.device_id === deviceId ? { ...d, managed } : d),
            };
        });
        try {
            await this.hass.callWS({
                type: "home_insights/set_device_managed",
                device_id: deviceId,
                managed,
            });
            this._toast = managed
                ? "Device suppressed. New patterns from it won't appear."
                : "Device restored. Future patterns from it will appear again.";
        }
        catch (err) {
            // Revert optimistic update
            this._insights = this._insights.map((i) => {
                if (!i.referenced_devices)
                    return i;
                if (!i.referenced_devices.some((d) => d.device_id === deviceId))
                    return i;
                return {
                    ...i,
                    referenced_devices: i.referenced_devices.map((d) => d.device_id === deviceId ? { ...d, managed: !managed } : d),
                };
            });
            this._toast = `Failed: ${this._asMessage(err)}`;
        }
    }
    /** Render an "🔁 already automated" or "🤖 in N automations" pill.
     *
     *  Single match (N=1): plain anchor + inline ✏️. Click = open the
     *  one matching automation. Fast path; no extra clicks.
     *
     *  Multiple matches (N>1): `<details>` expander where the summary IS
     *  the pill, and each automation appears below as its own clickable
     *  row with its own ✏️ Refine button. Native `<details>` gives us
     *  expand/collapse for free — no popover state, no click-outside
     *  handling. Earlier version silently picked the first link and the
     *  user couldn't reach the others; this fixes that.
     *
     *  No-id legacy YAML: same fallback as before — text only, no URL,
     *  Refine button hidden. */
    _renderAutomationPill(label, color, leadText, links) {
        const aliases = links.map((l) => l.alias);
        const tooltip = `${leadText}: ${aliases.join(", ")}`;
        // Single-link fast path. Keeps the row compact — most insights only
        // hit one automation, and forcing an extra click feels punitive.
        if (links.length <= 1) {
            const only = links[0];
            const url = only?.url ?? "/config/automation/dashboard";
            return b `<span class="automation-pill-group">
        <a
          class="pill"
          href=${url}
          target="_top"
          style="color: ${color}; text-decoration: none; cursor: pointer;"
          title="${tooltip} — click to open the automation editor"
          @click=${(e) => e.stopPropagation()}
        >${label}</a>
        ${only?.id
                ? b `<button
              class="pill-action"
              aria-label="Refine automation '${only.alias}' with AI"
              title="Refine this automation with AI"
              @click=${(e) => {
                    e.stopPropagation();
                    this._openRefineAutomationModal(only.id, only.alias);
                }}
            >✏️</button>`
                : A}
      </span>`;
        }
        // Multi-link expander. Native <details> handles the open/close state.
        return b `<details
      class="automation-pill-details"
      @click=${(e) => e.stopPropagation()}
    >
      <summary
        class="pill"
        style="color: ${color}; cursor: pointer; list-style: none;"
        title="${tooltip} — click to expand"
      >${label} ▾</summary>
      <div class="automation-pill-menu">
        ${links.map((link) => {
            const url = link.url ?? "/config/automation/dashboard";
            return b `<div class="automation-pill-row">
            <a
              class="automation-pill-link"
              href=${url}
              target="_top"
              title="Open '${link.alias}' in the automation editor"
              @click=${(e) => e.stopPropagation()}
            >${link.alias}</a>
            ${link.id
                ? b `<button
                  class="pill-action"
                  aria-label="Refine automation '${link.alias}' with AI"
                  title="Refine '${link.alias}' with AI"
                  @click=${(e) => {
                    e.stopPropagation();
                    this._openRefineAutomationModal(link.id, link.alias);
                }}
                >✏️</button>`
                : A}
          </div>`;
        })}
      </div>
    </details>`;
    }
    /** Open the refine-existing-automation modal. Loads the YAML via
     *  home_insights/get_automation, then shows the editor + feedback
     *  panel. Errors display inline in the modal. */
    async _openRefineAutomationModal(automationId, alias) {
        if (!this.hass)
            return;
        this._refineAutomationModal = {
            automationId,
            alias,
            feedback: "",
            busy: true,
        };
        try {
            const result = await this.hass.connection.sendMessagePromise({
                type: "home_insights/get_automation",
                automation_id: automationId,
            });
            this._refineAutomationModal = {
                ...this._refineAutomationModal,
                originalYaml: result.yaml,
                busy: false,
            };
        }
        catch (err) {
            this._refineAutomationModal = {
                ...this._refineAutomationModal,
                busy: false,
                error: `Could not load automation: ${this._asMessage(err)}`,
            };
        }
    }
    _toggleCohortExpansion(insightId) {
        const next = new Set(this._expandedCohorts);
        if (next.has(insightId)) {
            next.delete(insightId);
        }
        else {
            next.add(insightId);
        }
        this._expandedCohorts = next;
    }
    _closeRefineAutomationModal() {
        this._refineAutomationModal = undefined;
    }
    async _submitRefineAutomation() {
        if (!this.hass || !this._refineAutomationModal)
            return;
        const m = this._refineAutomationModal;
        if (!m.feedback.trim()) {
            this._refineAutomationModal = {
                ...m,
                error: "Add some feedback for the LLM (what should change?)",
            };
            return;
        }
        this._refineAutomationModal = { ...m, busy: true, error: undefined };
        try {
            const result = await this.hass.connection.sendMessagePromise({
                type: "home_insights/refine_automation",
                automation_id: m.automationId,
                feedback: m.feedback,
            });
            this._refineAutomationModal = {
                ...this._refineAutomationModal,
                busy: false,
                originalYaml: result.original_yaml,
                refinedYaml: result.refined_yaml,
                refinedConfig: result.refined_config,
                rationale: result.rationale,
                diffSummary: result.diff_summary,
                bytesSent: result.bytes_sent,
                bytesReceived: result.bytes_received,
            };
        }
        catch (err) {
            this._refineAutomationModal = {
                ...this._refineAutomationModal,
                busy: false,
                error: `Refine failed: ${this._asMessage(err)}`,
            };
        }
    }
    async _applyRefineAutomation() {
        if (!this.hass || !this._refineAutomationModal)
            return;
        const m = this._refineAutomationModal;
        if (!m.refinedConfig)
            return;
        this._refineAutomationModal = { ...m, busy: true, error: undefined };
        try {
            await this.hass.connection.sendMessagePromise({
                type: "home_insights/apply_automation_refinement",
                automation_id: m.automationId,
                refined_config: m.refinedConfig,
            });
            this._toast = `Applied refinement to '${m.alias}'`;
            this._refineAutomationModal = undefined;
        }
        catch (err) {
            this._refineAutomationModal = {
                ...this._refineAutomationModal,
                busy: false,
                error: `Apply failed: ${this._asMessage(err)}`,
            };
        }
    }
    /** IDE-style line diff. Computes a longest-common-subsequence over
     *  both YAML inputs, then renders an aligned two-column view where:
     *    - unchanged lines appear on BOTH sides at the same row
     *    - removed-only lines appear on the left, blank on the right
     *    - added-only lines appear on the right, blank on the left
     *
     *  Each row has a gutter showing line number + change marker
     *  (-, +, or space). That's the standard pattern in VS Code,
     *  GitHub PR view, etc. — far more readable for YAML diffs than
     *  the previous "tint lines not found in the other side" approach
     *  because rows actually line up across panes. */
    _renderSideBySideDiff(original, refined, leftLabel = "Current YAML", rightLabel = "Refined YAML") {
        const rows = this._alignDiffRows(original.split("\n"), refined.split("\n"));
        const cell = ({ lineNum, text, marker }, side) => {
            const bg = marker === "-"
                ? "rgba(244, 67, 54, 0.10)"
                : marker === "+"
                    ? "rgba(76, 175, 80, 0.12)"
                    : "transparent";
            const color = marker === "-"
                ? "var(--error-color, #c62828)"
                : marker === "+"
                    ? "var(--success-color, #2e7d32)"
                    : "var(--primary-text-color)";
            // Inert empty cell — keeps row alignment when one side has no
            // content for this row.
            if (text === null) {
                return b `<div
          style="background:${bg}; min-height:1.2em; border-right: 1px solid var(--divider-color, rgba(0,0,0,0.06));"
        ></div>`;
            }
            return b `<div
        style="background:${bg}; color:${color}; white-space:pre; min-height:1.2em; display:flex; gap:6px; font-family: var(--code-font-family, monospace); border-right: 1px solid var(--divider-color, rgba(0,0,0,0.06)); padding: 0 6px;"
      ><span
          style="opacity:0.4; user-select:none; min-width:3ch; text-align:right;"
        >${lineNum ?? ""}</span><span
          style="opacity:0.55; user-select:none; width:1ch;"
        >${marker}</span><span>${text || " "}</span></div>`;
        };
        return b `<div
      style="margin-bottom: 8px;"
    >
      <div
        class="diff-header"
        style="display:grid; grid-template-columns: 1fr 1fr; gap: 0; font-weight: 500; font-size:0.88em; margin-bottom: 4px;"
      >
        <div style="border-bottom: 2px solid var(--error-color, #c62828); padding-bottom: 2px;">
          ${leftLabel}
        </div>
        <div style="border-bottom: 2px solid var(--success-color, #4caf50); padding-bottom: 2px; padding-left: 8px;">
          ${rightLabel}
        </div>
      </div>
      <div
        class="diff-pane"
        style="max-height:55vh; overflow:auto; font-size:0.82em; background: var(--code-background-color, rgba(0,0,0,0.03)); border-radius: 4px; border: 1px solid var(--divider-color, rgba(0,0,0,0.10));"
      >
        <div class="diff-grid" style="display:grid; grid-template-columns: 1fr 1fr; gap: 0;">
          ${rows.map((r) => b `${cell({
            lineNum: r.leftLineNum,
            text: r.leftText,
            marker: r.leftMarker,
        })}${cell({
            lineNum: r.rightLineNum,
            text: r.rightText,
            marker: r.rightMarker,
        })}`)}
        </div>
      </div>
    </div>`;
    }
    /** Compute aligned diff rows using LCS line matching. Returns an
     *  array where each row has both a left and right cell — empty
     *  on one side means the line was inserted/deleted there.
     *
     *  Algorithm: standard O(m*n) LCS table over line equality, then
     *  walk backwards to reconstruct the diff. For automation YAMLs
     *  (typically 20-200 lines) the dp table is tiny — milliseconds
     *  even on a Raspberry Pi. */
    _alignDiffRows(a, b) {
        const m = a.length;
        const n = b.length;
        // dp[i][j] = LCS length of a[0..i) vs b[0..j)
        const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
        for (let i = 1; i <= m; i++) {
            for (let j = 1; j <= n; j++) {
                if (a[i - 1] === b[j - 1]) {
                    dp[i][j] = dp[i - 1][j - 1] + 1;
                }
                else {
                    dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
                }
            }
        }
        const ops = [];
        let i = m;
        let j = n;
        while (i > 0 && j > 0) {
            if (a[i - 1] === b[j - 1]) {
                ops.push({ type: "=", a: i - 1, b: j - 1 });
                i--;
                j--;
            }
            else if (dp[i - 1][j] >= dp[i][j - 1]) {
                ops.push({ type: "-", a: i - 1 });
                i--;
            }
            else {
                ops.push({ type: "+", b: j - 1 });
                j--;
            }
        }
        while (i > 0) {
            ops.push({ type: "-", a: i - 1 });
            i--;
        }
        while (j > 0) {
            ops.push({ type: "+", b: j - 1 });
            j--;
        }
        ops.reverse();
        // Convert flat ops into aligned rows. Consecutive `-` and `+`
        // ops get paired (one on each side); leftover ones get a blank
        // cell on the opposite side.
        const rows = [];
        let k = 0;
        while (k < ops.length) {
            const op = ops[k];
            if (op.type === "=") {
                rows.push({
                    leftLineNum: op.a + 1,
                    leftText: a[op.a],
                    leftMarker: " ",
                    rightLineNum: op.b + 1,
                    rightText: b[op.b],
                    rightMarker: " ",
                });
                k++;
                continue;
            }
            // Group a run of - and + ops, then pair them up
            const minus = [];
            const plus = [];
            while (k < ops.length && ops[k].type !== "=") {
                const o = ops[k];
                if (o.type === "-")
                    minus.push(o.a);
                else
                    plus.push(o.b);
                k++;
            }
            const max = Math.max(minus.length, plus.length);
            for (let p = 0; p < max; p++) {
                const lh = p < minus.length ? minus[p] : null;
                const rh = p < plus.length ? plus[p] : null;
                rows.push({
                    leftLineNum: lh !== null ? lh + 1 : null,
                    leftText: lh !== null ? a[lh] : null,
                    leftMarker: lh !== null ? "-" : " ",
                    rightLineNum: rh !== null ? rh + 1 : null,
                    rightText: rh !== null ? b[rh] : null,
                    rightMarker: rh !== null ? "+" : " ",
                });
            }
        }
        return rows;
    }
    /** Render a token-usage pill row under the rationale.
     *
     *  We get byte counts from the backend, not exact token counts —
     *  the HA Conversation API doesn't surface provider-side token
     *  metering, so we estimate via the standard ~4 chars/token rule
     *  used by both OpenAI and Anthropic tokenizer docs. Labelled
     *  "≈" to flag the approximation.
     *
     *  Returns nothing for the cached / deterministic-preview path
     *  (bytes_sent === 0 means we never made an LLM call).
     */
    _renderTokenUsage(bytesSent, bytesReceived) {
        if (!bytesSent && !bytesReceived)
            return A;
        const inTokens = Math.round((bytesSent ?? 0) / 4);
        const outTokens = Math.round((bytesReceived ?? 0) / 4);
        if (inTokens === 0 && outTokens === 0)
            return A;
        return b `<div
      style="margin: -6px 0 12px 0; font-size: 0.8em; color: var(--secondary-text-color);"
      title="Token counts are approximate (estimated from response byte length ÷ 4). HA's Conversation API doesn't expose provider-side token meters; bytes_sent/bytes_received are what we measure."
    >
      ≈ ${inTokens.toLocaleString()} in / ${outTokens.toLocaleString()} out tokens
      (${(bytesSent ?? 0).toLocaleString()}B sent · ${(bytesReceived ?? 0).toLocaleString()}B received)
    </div>`;
    }
    _renderRefineAutomationModal() {
        const m = this._refineAutomationModal;
        if (!m)
            return A;
        return b `<div
      class="dialog-backdrop"
      @click=${this._closeRefineAutomationModal}
    >
      <div
        class="dialog dialog-wide"
        @click=${(e) => e.stopPropagation()}
      >
        <div class="dialog-header">
          <div class="dialog-title">
            ${m.refinedSource === "deterministic"
            ? b `📋 Preview deterministic fix for '${m.alias}'`
            : m.refinedSource === "stage-two"
                ? b `📋 + 🤖 Algorithm + LLM refine of '${m.alias}'`
                : b `✏️ Refine '${m.alias}' with AI`}
          </div>
          <button
            class="dialog-close"
            aria-label="Close"
            @click=${this._closeRefineAutomationModal}
          >×</button>
        </div>
        <div class="dialog-body">
          ${m.error
            ? b `<div
                class="error-banner"
                style="margin-bottom: 12px; border-radius: 6px;"
              >${m.error}</div>`
            : A}
          ${m.busy
            ? b `<div style="padding: 12px;">⏳ Working…</div>`
            : A}
          ${!m.refinedYaml && !m.busy
            ? b `
                <div style="margin-bottom: 8px; font-weight: 500;">
                  Current automation
                </div>
                ${m.originalYaml
                ? b `<pre
                      style="max-height: 280px; overflow: auto; background: var(--code-background-color, rgba(0,0,0,0.04)); padding: 12px; border-radius: 4px; font-size: 0.85em;"
                    >${m.originalYaml}</pre>`
                : b `<div
                      style="padding: 10px; margin-bottom: 8px; background: rgba(255, 152, 0, 0.10); border-left: 3px solid var(--warning-color, #ff9800); border-radius: 4px; font-size: 0.9em;"
                    >⚠️ Couldn't load the automation's YAML. HA's
                    automation registry returned an empty record for
                    this id. You can still describe a change below,
                    but the LLM won't have the existing YAML for
                    context — quality of the suggestion will be lower.</div>`}
                <div style="margin-top: 16px; margin-bottom: 8px; font-weight: 500;">
                  What should change?
                </div>
                <textarea
                  rows="4"
                  style="width: 100%; padding: 8px; box-sizing: border-box; font-family: inherit;"
                  placeholder="e.g. 'Move the trigger 10 minutes earlier' or 'Skip on weekends' or 'Add a notification when it fires'"
                  .value=${m.feedback}
                  @input=${(e) => {
                if (this._refineAutomationModal) {
                    this._refineAutomationModal = {
                        ...this._refineAutomationModal,
                        feedback: e.target.value,
                    };
                }
            }}
                  ?disabled=${m.busy}
                ></textarea>
              `
            : A}
          ${m.refinedYaml
            ? b `
                ${m.rationale
                ? b `<div
                      style="margin-bottom: 12px; padding: 10px; background: var(--info-background-color, rgba(33, 150, 243, 0.08)); border-left: 3px solid var(--info-color, #2196f3); border-radius: 4px;"
                    ><strong>Why these changes:</strong> ${m.rationale}</div>`
                : A}
                ${this._renderTokenUsage(m.bytesSent, m.bytesReceived)}
                ${m.diffSummary && m.diffSummary.length > 0
                ? b `<ul
                      style="margin: 0 0 12px 0; padding-left: 20px;"
                    >${m.diffSummary.map((line) => b `<li>${line}</li>`)}</ul>`
                : A}
                ${this._renderSideBySideDiff(m.originalYaml ?? "", m.refinedYaml, m.refinedSource === "stage-two"
                ? "Algorithm Output (stage 1)"
                : m.refinedSource === "deterministic"
                    ? "Current YAML (live)"
                    : "Current YAML", m.refinedSource === "deterministic"
                ? "Algorithm Fix (no LLM)"
                : m.refinedSource === "stage-two"
                    ? "LLM Refinement (stage 2)"
                    : "Refined by LLM")}
              `
            : A}
        </div>
        ${m.refinedYaml && m.auditInsightId
            ? b `<div
              style="border-top: 1px solid var(--divider-color, rgba(0,0,0,0.1)); padding: 10px 16px; background: var(--secondary-background-color, rgba(0,0,0,0.02));"
              @click=${(e) => e.stopPropagation()}
            >
              <div style="font-size: 0.85em; font-weight: 500; margin-bottom: 4px;">
                ${m.refinedSource === "deterministic"
                ? "🤖 Take this further with the LLM?"
                : "🤖 Refine again with more guidance?"}
              </div>
              <textarea
                rows="2"
                style="width: 100%; padding: 6px 8px; box-sizing: border-box; font-family: inherit; font-size: 0.88em;"
                placeholder=${m.refinedSource === "deterministic"
                ? "Optional — describe any extra changes (e.g. 'also disable on holidays', 'add a notification')"
                : "Optional follow-up feedback for another LLM pass…"}
                .value=${m.feedback}
                @input=${(e) => {
                if (this._refineAutomationModal) {
                    this._refineAutomationModal = {
                        ...this._refineAutomationModal,
                        feedback: e.target.value,
                    };
                }
            }}
                ?disabled=${m.busy}
              ></textarea>
              <div style="display: flex; justify-content: flex-end; margin-top: 6px;">
                <button
                  class="pill-action"
                  ?disabled=${m.busy}
                  @click=${this._refineFurtherWithLlm}
                  title="${m.refinedSource === 'deterministic'
                ? 'Send the algorithm result + your extra feedback to the LLM for further refinement (uses tokens).'
                : 'Send the current refined YAML + your follow-up back through the LLM.'}"
                >${m.busy
                ? "Thinking…"
                : m.refinedSource === "deterministic"
                    ? "🤖 Refine further with LLM"
                    : "🤖 Refine again"}</button>
              </div>
            </div>`
            : A}
        <div class="dialog-footer">
          ${!m.refinedYaml
            ? b `<button
                @click=${this._submitRefineAutomation}
                ?disabled=${m.busy || !m.feedback.trim()}
              >${m.busy ? "Refining…" : "Refine with AI"}</button>`
            : b `
                <button
                  @click=${() => {
                if (this._refineAutomationModal) {
                    this._refineAutomationModal = {
                        ...this._refineAutomationModal,
                        refinedYaml: undefined,
                        refinedConfig: undefined,
                        rationale: undefined,
                        diffSummary: undefined,
                    };
                }
            }}
                  ?disabled=${m.busy}
                >Discard</button>
                <button
                  class="primary"
                  @click=${this._applyRefineAutomation}
                  ?disabled=${m.busy}
                  title=${m.refinedSource === "deterministic"
                ? "Write the algorithm's deterministic fix to automations.yaml"
                : m.refinedSource === "stage-two"
                    ? "Write the LLM's stage-2 refinement to automations.yaml"
                    : "Write this refined YAML to automations.yaml"}
                >${m.busy
                ? "Applying…"
                : m.refinedSource === "deterministic"
                    ? "Apply algorithm fix"
                    : m.refinedSource === "stage-two"
                        ? "Apply stage-2 result"
                        : "Apply refinement"}</button>
              `}
        </div>
      </div>
    </div>`;
    }
    /** Render insight.created_at as a relative-time pill ("3h ago" / "yesterday").
     *  Returns "" for very fresh (<5min) so we don't clutter brand-new rows. */
    _formatAge(createdAt) {
        if (!createdAt)
            return "";
        const created = new Date(createdAt).getTime();
        if (Number.isNaN(created))
            return "";
        const seconds = Math.floor((Date.now() - created) / 1000);
        if (seconds < 5 * 60)
            return "";
        if (seconds < 60 * 60) {
            const m = Math.floor(seconds / 60);
            return `${m}m ago`;
        }
        if (seconds < 24 * 60 * 60) {
            const h = Math.floor(seconds / 3600);
            return `${h}h ago`;
        }
        const days = Math.floor(seconds / (24 * 60 * 60));
        if (days === 1)
            return "yesterday";
        if (days < 14)
            return `${days}d ago`;
        const weeks = Math.floor(days / 7);
        return `${weeks}w ago`;
    }
    /** Per-row trust indicator. Mirrors the header privacy mode but at row
     *  level so users have a constant reminder of what *any* LLM action on
     *  this row will do. Suppressed in OFF mode (no LLM = no trust concern).
     */
    /**
     * Maturity pill — shows BETA / EXPERIMENTAL when the insight comes
     * from a detector that hasn't been field-tested yet. STABLE insights
     * get no pill (no chrome for the default case). Sets honest
     * expectations so users know "this output might be wrong, please
     * tell us" vs "this should be reliable."
     *
     * Sources `insight.maturity` (field on the Insight dataclass, set
     * from the Detector class at scan time, surfaced via ws_list +
     * subscribe).
     */
    _renderMaturityPill(insight) {
        const maturity = insight.maturity;
        if (!maturity || maturity === "stable")
            return A;
        if (maturity === "beta") {
            return b `
        <span
          class="pill"
          style="background: rgba(255, 193, 7, 0.18); color: #b8860b;"
          title="BETA — this detector ships but hasn't been field-tested across diverse installs. Insights may have edge-case false positives. Dismiss feedback helps promote it to STABLE."
        >🟡 BETA</span>
      `;
        }
        if (maturity === "experimental") {
            return b `
        <span
          class="pill"
          style="background: rgba(156, 39, 176, 0.18); color: #6a1b9a;"
          title="EXPERIMENTAL — this detector is new. Output may be inaccurate or noisy. Was this useful? Dismiss or apply to teach the project what works."
        >🧪 EXPERIMENTAL</span>
      `;
        }
        return A;
    }
    _renderTrustPill() {
        const mode = this._hello?.privacy_mode;
        if (!mode || mode === "off")
            return A;
        if (mode === "local") {
            return b `
        <span
          class="pill"
          style="background: rgba(76, 175, 80, 0.18); color: var(--success-color, #2e7d32);"
          title="LLM actions on this insight stay on your local network"
        >🟢 local</span>
      `;
        }
        return b `
      <span
        class="pill"
        style="background: rgba(255, 152, 0, 0.18); color: var(--warning-color, #e65100);"
        title="LLM actions on this insight send pseudonymized data to a cloud LLM"
      >🟡 cloud</span>
    `;
    }
    _renderDiff(diff) {
        return b `
      <ul class="diff-list">
        ${diff.map((line) => {
            const cls = line.startsWith("+")
                ? "diff-add"
                : line.startsWith("-")
                    ? "diff-remove"
                    : "diff-change";
            return b `<li class=${cls}>${line}</li>`;
        })}
      </ul>
    `;
    }
    _renderFeedbackInput(insight, label) {
        const feedback = this._feedbackById.get(insight.id) ?? "";
        return b `
      <div class="feedback">
        <h5>${label}</h5>
        <textarea
          placeholder="e.g. Add a sun.below_horizon condition; change debounce to 10s; only run when nobody is home"
          .value=${feedback}
          @input=${(e) => {
            const value = e.target.value;
            const next = new Map(this._feedbackById);
            if (value)
                next.set(insight.id, value);
            else
                next.delete(insight.id);
            this._feedbackById = next;
        }}
        ></textarea>
      </div>
    `;
    }
    _renderRefinedPreview(insight, refined) {
        const busy = this._busyId === insight.id;
        return b `
      <div class="refined-banner">
        <strong>✨ Refined version proposed</strong>
        ${refined.rationale ?? "(no rationale provided)"}
        ${refined.diffSummary.length > 0
            ? this._renderDiff(refined.diffSummary)
            : b `<div style="margin-top: 6px; font-style: italic;">
              No top-level changes detected.
            </div>`}
      </div>
      <h4>Original vs refined</h4>
      <div class="compare">
        <div class="compare-col">
          <h5>Original</h5>
          <pre>${JSON.stringify(insight.payload, null, 2)}</pre>
        </div>
        <div class="compare-col refined">
          <h5>Refined</h5>
          <pre>${JSON.stringify(refined.payload, null, 2)}</pre>
        </div>
      </div>
      <h4>Edit refined before Apply</h4>
      ${this._renderPayloadView(insight, refined.payload)}
      ${this._renderPreview(insight)}
      ${this._renderRename(insight, refined)}
      ${this._renderFeedbackInput(insight, "Ask the LLM for further changes")}
      <div class="explain-row">
        <button
          class="action ${this._refineBusy ? "busy-pulse" : ""}"
          ?disabled=${this._refineBusy}
          @click=${() => this._refine(insight)}
        >
          ${this._refineBusy
            ? "💭 refining…"
            : `Refine again (turn ${(this._refineTurnsById.get(insight.id) ?? 0) + 1})`}
        </button>
        <button
          class="action"
          ?disabled=${this._testBusy}
          title="Fire the refined action(s) for real"
          @click=${() => this._testActions(insight, refined.payload)}
        >
          ${this._testBusy ? "testing…" : "🔥 Test refined"}
        </button>
        <button class="action" @click=${() => this._keepOriginal(insight.id)}>
          Keep original
        </button>
      </div>
      <div class="dialog-footer">
        <button class="action" ?disabled=${busy} @click=${() => this._dismiss(insight)}>
          Dismiss
        </button>
        <button
          class="action primary"
          ?disabled=${busy}
          @click=${() => this._apply(insight, refined.payload)}
        >
          ${busy ? "applying…" : "Apply refined"}
        </button>
      </div>
    `;
    }
    /**
     * v1.5.11 — Setup-guide dialog body for setup_quality insights.
     *
     * Why this exists separately from the generic dialog body: the
     * default body assumes the insight has YAML to refine/apply. It
     * shows a JSON payload editor, "Customize" rename form, "Notes
     * for the LLM" textarea, etc. setup_quality insights are
     * observational — they tell the user "wire X to unlock detector
     * Y". The actionable surface is a deep-link to the right HA
     * settings page, not a YAML editor.
     *
     * Handles BOTH:
     *   - summary insights (fingerprint.kind = "setup_quality_summary")
     *     payload contains `setup_steps` — a full per-feature roll-up.
     *   - per-feature insights (fingerprint.kind = "setup_quality_feature")
     *     payload contains single-feature shape — we synthesize a
     *     one-item list so the same renderer handles both.
     */
    _renderSetupGuideBody(insight) {
        const busy = this._busyId === insight.id;
        const confidencePct = Math.round(insight.confidence * 100);
        const payload = (insight.payload ?? {});
        const steps = Array.isArray(payload.setup_steps)
            ? payload.setup_steps
            : payload.feature_key
                ? [
                    {
                        feature: payload.feature,
                        feature_key: payload.feature_key,
                        tier: payload.tier,
                        advice: payload.advice ?? "",
                        next_step: payload.next_step ?? "",
                        scenarios: payload.scenarios_unlocked ?? [],
                        setup_url: payload.setup_url ?? null,
                        setup_url_label: payload.setup_url_label ?? null,
                        setup_url_external: !!payload.setup_url_external,
                    },
                ]
                : [];
        const scorePct = typeof payload.score === "number"
            ? Math.round(payload.score * 100)
            : null;
        return b `
      <div class="dialog-body setup-guide-body">
        ${this._renderModalError()}
        <div class="row-meta">
          <span class="pill">confidence ${confidencePct}%</span>
          <span class="pill">${insight.detector}</span>
          ${scorePct !== null
            ? b `<span class="pill">${scorePct}% complete</span>`
            : A}
        </div>
        ${insight.explanation
            ? b `<div class="explanation">${insight.explanation}</div>`
            : A}
        ${steps.length > 0
            ? b `
              <h4 style="margin-top:16px;">Features &amp; setup steps</h4>
              <div class="setup-steps">
                ${steps.map((s) => this._renderSetupStep(s))}
              </div>
            `
            : b `
              <div class="setup-stale-banner">
                <strong>This insight was created before v1.5.11.</strong>
                Re-scan to populate per-feature setup steps with deep-link
                buttons. Until then, the actions live inline in the
                explanation above.
                <div class="setup-stale-action">
                  <button
                    class="action primary"
                    ?disabled=${this._scanBusy}
                    @click=${this._runScanNow}
                    title="Refresh insights — regenerates this card with deep-link buttons for each setup step"
                  >
                    ${this._scanBusy ? "Scanning…" : "🔍 Run scan now"}
                  </button>
                </div>
              </div>
            `}
        <div class="subtitle" style="margin-top:12px;">
          After changing a setting, run Settings → Devices &amp; Services →
          HA Insights → <em>Scan now</em> to refresh setup completeness.
        </div>
      </div>
      <div class="dialog-footer">
        <button class="action" ?disabled=${busy} @click=${() => this._dismiss(insight)}>
          Dismiss
        </button>
        <button class="action" ?disabled=${busy} @click=${() => this._snooze(insight)}>
          Snooze 7d
        </button>
        <button
          class="action retire"
          ?disabled=${busy}
          title="Permanently retire this suggestion — won't appear again unless un-retired from the history view"
          @click=${() => this._retire(insight)}
        >
          Retire
        </button>
      </div>
    `;
    }
    /** v1.2.16 — Dedicated dialog body for automation_audit insights.
     *
     *  Pre-v1.2.16 audit insights shared the generic Refine-flow body,
     *  which:
     *    - Surfaced raw JSON payload front and center (the user has no
     *      use for the internal observation list shape).
     *    - Showed a Customize block (Alias / Description / "Notes for
     *      the LLM") that renames the *insight* — meaningless for an
     *      audit observation that already names an automation by alias.
     *    - Buried 🤖 Suggest improvements at the bottom and offered no
     *      direct link to the automation it was complaining about.
     *
     *  v1.2.16 renders observations as a structured list with per-kind
     *  icons + actions, promotes 🤖 Suggest as the primary CTA, and
     *  exposes a deeplink to /config/automation/edit/{automation_id}
     *  for the "fix it manually" path. Raw payload moves behind a
     *  <details> disclosure for power users. Apply ─ which is a no-op
     *  for an observation-only audit ─ is hidden entirely. */
    /** v1.12.8 — Specialized body renderer for v1.7+ detectors that
     *  use `payload_format="card"` but were previously falling through
     *  to the generic _renderPayloadView (raw JSON dump in the modal).
     *
     *  Dispatches on payload key (`_state_shift` / `_physical_device_link`
     *  / `_location_proposal`) to a per-type formatted body. New
     *  detectors that add a `_<name>` key to their payload should get a
     *  matching branch added here. Returns `nothing` when no
     *  specialized renderer matches — caller falls back to generic.
     *
     *  Why dispatch on payload key vs detector name: detector renaming
     *  shouldn't break the renderer, and the payload key is the
     *  contract the integration's CHANGELOG advertises (e.g. v1.11.0
     *  added "_physical_device_link" block).
     */
    _hasSpecializedCardRenderer(insight) {
        const payload = (insight.payload ?? {});
        return !!(payload._state_shift ||
            payload._physical_device_link ||
            payload._location_proposal);
    }
    _renderCardBody(insight) {
        const payload = (insight.payload ?? {});
        if (payload._state_shift) {
            return this._renderStateShiftBody(insight, payload._state_shift);
        }
        if (payload._physical_device_link) {
            return this._renderPhysicalDeviceLinkBody(insight, payload._physical_device_link);
        }
        if (payload._location_proposal) {
            return this._renderLocationProposalBody(insight, payload._location_proposal);
        }
        return A;
    }
    /** v1.8.2 StateShiftDetector — "Daily-count for X shifted on YYYY-MM-DD." */
    _renderStateShiftBody(insight, block) {
        const shiftDate = block.shift_date ?? "(unknown date)";
        const preMean = block.pre_shift_mean_per_day;
        const postMean = block.post_shift_mean_per_day;
        const daysAgo = block.days_ago;
        const magnitude = block.magnitude;
        const confidencePct = Math.round(insight.confidence * 100);
        return b `
      <div class="dialog-body">
        ${this._renderModalError()}
        <div class="row-meta">
          <span class="pill">confidence ${confidencePct}%</span>
          <span class="pill">state shift</span>
          ${insight.maturity === "beta"
            ? b `<span class="pill" style="color: var(--warning-color)">🟡 BETA</span>`
            : A}
        </div>
        <h4>Routine shift detected</h4>
        <div class="state-shift-summary">
          <div class="state-shift-line">
            <span class="state-shift-label">Date:</span>
            <span class="state-shift-value">${shiftDate}${daysAgo != null ? b ` (~${daysAgo} days ago)` : A}</span>
          </div>
          <div class="state-shift-line">
            <span class="state-shift-label">Before:</span>
            <span class="state-shift-value">${preMean != null ? b `~${preMean.toFixed(1)}/day` : "—"}</span>
          </div>
          <div class="state-shift-line">
            <span class="state-shift-label">After:</span>
            <span class="state-shift-value">${postMean != null ? b `~${postMean.toFixed(1)}/day` : "—"}</span>
          </div>
          ${magnitude != null
            ? b `<div class="state-shift-line">
                <span class="state-shift-label">Shift magnitude:</span>
                <span class="state-shift-value">${magnitude.toFixed(1)}</span>
              </div>`
            : A}
        </div>
        ${insight.explanation
            ? b `<div class="explanation">${insight.explanation}</div>`
            : A}
      </div>
    `;
    }
    /** v1.11.0 PhysicalDeviceLinkDetector — "X and Y look like the same physical device." */
    _renderPhysicalDeviceLinkBody(insight, block) {
        // v1.12.7 rename: entity_id / peer_entity_id (canonical sort).
        // Older insights stored entity_a / entity_b — handle both for
        // backward compat with cached insights from pre-v1.12.7 server.
        const entityId = block.entity_id ??
            block.entity_a ??
            "?";
        const peerEntityId = block.peer_entity_id ??
            block.entity_b ??
            "?";
        const r = block.pearson_r;
        const nSamples = block.n_aligned_samples;
        const bestLagBins = block.best_lag_bins;
        const deviceClass = block.device_class ?? "—";
        const lookbackDays = block.lookback_days;
        const confidencePct = Math.round(insight.confidence * 100);
        return b `
      <div class="dialog-body">
        ${this._renderModalError()}
        <div class="row-meta">
          <span class="pill">confidence ${confidencePct}%</span>
          <span class="pill">device link</span>
          ${insight.maturity === "beta"
            ? b `<span class="pill" style="color: var(--warning-color)">🟡 BETA</span>`
            : A}
        </div>
        <h4>These look like the same physical device</h4>
        <div class="device-link-pair">
          <code class="device-link-eid">${entityId}</code>
          <span class="device-link-arrow">↔</span>
          <code class="device-link-eid">${peerEntityId}</code>
        </div>
        <div class="state-shift-summary">
          <div class="state-shift-line">
            <span class="state-shift-label">Pearson r:</span>
            <span class="state-shift-value">${r != null ? r.toFixed(3) : "—"}</span>
          </div>
          <div class="state-shift-line">
            <span class="state-shift-label">Aligned samples:</span>
            <span class="state-shift-value">${nSamples ?? "—"} (${lookbackDays ?? "?"}-day lookback)</span>
          </div>
          <div class="state-shift-line">
            <span class="state-shift-label">Device class:</span>
            <span class="state-shift-value">${deviceClass}</span>
          </div>
          ${bestLagBins != null && bestLagBins !== 0
            ? b `<div class="state-shift-line">
                <span class="state-shift-label">Detected at lag:</span>
                <span class="state-shift-value">${bestLagBins} bin${bestLagBins === 1 || bestLagBins === -1 ? "" : "s"} (likely clock drift between integrations)</span>
              </div>`
            : A}
        </div>
        ${insight.explanation
            ? b `<div class="explanation">${insight.explanation}</div>`
            : A}
      </div>
    `;
    }
    /** v1.11.5 LocationProposalDetector — "X is probably in Living Room." */
    _renderLocationProposalBody(insight, block) {
        const entityId = block.entity_id ?? "?";
        const areaName = block.proposed_area_name ?? "?";
        const medianR = block.median_r;
        const nSiblings = block.n_siblings;
        const deviceClass = block.device_class ?? "—";
        const alternatives = block.alternatives ?? [];
        const confidencePct = Math.round(insight.confidence * 100);
        const strength = medianR != null && medianR >= 0.9 ? "Almost certainly" : "Probably";
        return b `
      <div class="dialog-body">
        ${this._renderModalError()}
        <div class="row-meta">
          <span class="pill">confidence ${confidencePct}%</span>
          <span class="pill">location proposal</span>
          ${insight.maturity === "beta"
            ? b `<span class="pill" style="color: var(--warning-color)">🟡 BETA</span>`
            : A}
        </div>
        <h4>${strength} in ${areaName}</h4>
        <div class="location-proposal-summary">
          <div>
            <code>${entityId}</code> matches
            ${nSiblings ?? "?"} tagged ${deviceClass}
            ${nSiblings === 1 ? "sibling" : "siblings"} at median
            r=${medianR != null ? medianR.toFixed(2) : "?"}.
          </div>
        </div>
        ${alternatives.length > 0
            ? b `
              <h4>Alternative areas considered</h4>
              <ul class="location-alt-list">
                ${alternatives.map((alt) => b `
                    <li>
                      <code>${alt.area_id ?? "?"}</code> —
                      r=${alt.median_r != null ? alt.median_r.toFixed(2) : "?"}
                      across ${alt.n_siblings ?? "?"} sibling${alt.n_siblings === 1 ? "" : "s"}
                    </li>
                  `)}
              </ul>
            `
            : A}
        ${insight.explanation
            ? b `<div class="explanation">${insight.explanation}</div>`
            : A}
        <p class="location-proposal-note">
          <strong>Advisory only.</strong> This detector never auto-assigns areas.
          Confirm the suggestion via the bulk-area-assign dialog or override
          with a different area.
        </p>
      </div>
    `;
    }
    _renderAuditBody(insight) {
        const busy = this._busyId === insight.id || this._auditSuggestBusy === insight.id;
        const confidencePct = Math.round(insight.confidence * 100);
        const payload = (insight.payload ?? {});
        const automationAlias = payload.automation_alias ?? "";
        const automationId = payload.automation_id ?? "";
        const advice = payload.advice ?? "";
        const observations = Array.isArray(payload.observations)
            ? payload.observations.filter((o) => typeof o === "object" && o !== null)
            : [];
        const targetEntities = Array.isArray(payload.target_entities)
            ? payload.target_entities.filter((e) => typeof e === "string")
            : [];
        const triggerEntities = Array.isArray(payload.trigger_entities)
            ? payload.trigger_entities.filter((e) => typeof e === "string")
            : [];
        const relatedIds = Array.isArray(payload.related_insight_ids)
            ? payload.related_insight_ids.filter((s) => typeof s === "string")
            : [];
        // entity_ids the audit has flagged as missing/silent so we can
        // mark them on the entity-pill list. Dedup'd Set lookup keeps
        // the per-pill check O(1).
        const silentEntities = new Set();
        for (const o of observations) {
            if (o.kind === "entity_silent"
                && o.metrics
                && typeof o.metrics.entity_id === "string") {
                silentEntities.add(o.metrics.entity_id);
            }
        }
        const editorUrl = automationId
            ? `/config/automation/edit/${automationId}`
            : "";
        return b `
      <div class="dialog-body audit-body">
        ${this._renderModalError()}
        <div class="row-meta">
          <span class="pill">confidence ${confidencePct}%</span>
          <span class="pill">automation_audit</span>
          ${insight.maturity === "beta"
            ? b `<span class="pill" style="color: var(--warning-color)">🟡 BETA</span>`
            : A}
        </div>
        ${automationAlias
            ? b `
              <div class="audit-automation-header">
                <div class="audit-automation-name">${automationAlias}</div>
                ${editorUrl
                ? b `<a
                      class="action primary"
                      href=${editorUrl}
                      target="_top"
                      title="Jump straight to this automation in HA's editor — fix it manually here"
                    >Open in editor →</a>`
                : A}
              </div>
            `
            : A}
        ${advice
            ? b `<div class="audit-advice">${advice}</div>`
            : A}
        ${observations.length > 0
            ? b `
              <h4 style="margin: 16px 0 4px 0;">
                Findings (${observations.length})
              </h4>
              <ul class="audit-findings">
                ${observations.map((o) => this._renderAuditFinding(o))}
              </ul>
            `
            : A}
        ${triggerEntities.length > 0 || targetEntities.length > 0
            ? b `
              <h4 style="margin: 16px 0 4px 0;">Entities</h4>
              <div class="audit-entity-grid">
                ${triggerEntities.length > 0
                ? b `
                      <div>
                        <div class="audit-entity-label">Trigger</div>
                        <div class="audit-entity-pills">
                          ${triggerEntities.map((e) => this._renderAuditEntityPill(e, silentEntities.has(e)))}
                        </div>
                      </div>
                    `
                : A}
                ${targetEntities.length > 0
                ? b `
                      <div>
                        <div class="audit-entity-label">Target</div>
                        <div class="audit-entity-pills">
                          ${targetEntities.map((e) => this._renderAuditEntityPill(e, silentEntities.has(e)))}
                        </div>
                      </div>
                    `
                : A}
              </div>
            `
            : A}
        ${relatedIds.length > 0
            ? b `
              <h4 style="margin: 16px 0 4px 0;">
                Related insights (${relatedIds.length})
              </h4>
              <div class="audit-related">
                ${relatedIds.map((id) => {
                const related = this._insights.find((i) => i.id === id);
                const label = related
                    ? this._displayTitle(related)
                    : `<${id.slice(0, 12)}…>`;
                return b `
                    <a
                      class="audit-related-link"
                      href="#"
                      @click=${(e) => {
                    e.preventDefault();
                    if (related)
                        this._openDialog(related.id);
                }}
                    >${label}</a>
                  `;
            })}
              </div>
            `
            : A}
        ${insight.explanation
            ? b `<div class="explanation">${insight.explanation}</div>`
            : A}
        <details class="audit-raw-payload">
          <summary>Show raw payload</summary>
          <pre class="payload-code">${JSON.stringify(insight.payload, null, 2)}</pre>
        </details>
      </div>
      <div class="dialog-footer">
        <button
          class="action primary"
          ?disabled=${busy}
          @click=${() => this._runAuditSuggest(insight)}
          title="Ask the LLM for specific YAML edits to fix these findings"
        >${this._auditSuggestBusy === insight.id
            ? "Thinking…"
            : "🤖 Suggest improvements"}</button>
        <button
          class="action"
          ?disabled=${busy}
          @click=${() => this._dismiss(insight)}
        >Dismiss</button>
        <button
          class="action"
          ?disabled=${busy}
          @click=${() => this._snooze(insight)}
        >Snooze 7d</button>
        <button
          class="action retire"
          ?disabled=${busy}
          title="Permanently retire this suggestion — won't appear again unless un-retired from the history view"
          @click=${() => this._retire(insight)}
        >Retire</button>
      </div>
    `;
    }
    /** One audit observation row. Kind-aware icon + a context action
     *  (entity link / scroll to editor / linked insight) so the user
     *  can act on each finding without leaving the dialog. */
    _renderAuditFinding(o) {
        const kindIcons = {
            entity_silent: "🔴",
            redundant_target: "🔁",
            long_on_duration: "⏱️",
            trigger_time_drift: "🕒",
            trace_dormant: "💤",
            trace_condition_blocks: "🚧",
            trace_action_errors: "❗",
            has_recent_insights: "📌",
            rollup_dow: "📅",
            rollup_dom: "📆",
            rollup_month: "🗓️",
            entity_stale_state: "🥶",
            cross_integration_coupling: "🌩️",
        };
        const icon = kindIcons[o.kind] ?? "•";
        const eid = typeof o.metrics?.entity_id === "string" ? o.metrics.entity_id : "";
        // Per-kind context action — small inline link so the user can act
        // on this specific finding without leaving the dialog.
        let action = A;
        if (o.kind === "entity_silent" && eid) {
            const url = `/config/entities?config_entry=&domain=&q=${encodeURIComponent(eid)}`;
            action = b `
        <a
          class="audit-finding-action"
          href=${url}
          target="_top"
          title="Open Entity Registry filtered to '${eid}' so you can rename, remove, or replace it"
        >Open entity →</a>
      `;
        }
        return b `
      <li class="audit-finding audit-finding--${o.kind}">
        <span class="audit-finding-icon">${icon}</span>
        <span class="audit-finding-text">${o.text}</span>
        ${action}
      </li>
    `;
    }
    /** Compact pill for an entity_id under Trigger / Target. The silent
     *  flag adds a red dot so the user spots the offending entity at a
     *  glance without scanning the findings list. */
    _renderAuditEntityPill(eid, silent) {
        return b `
      <span class="audit-entity-pill ${silent ? "is-silent" : ""}">
        ${silent ? b `<span class="silent-dot" title="Flagged silent / missing">●</span> ` : A}
        ${eid}
      </span>
    `;
    }
    _renderSetupStep(step) {
        const tier = step.tier ?? "USELESS";
        const tierBadge = {
            GREAT: { emoji: "✅", label: "Working great", cls: "ok" },
            GOOD: { emoji: "🟢", label: "Working", cls: "ok" },
            LIMITED: { emoji: "🟠", label: "Partial", cls: "warn" },
            USELESS: { emoji: "🔴", label: "Not configured", cls: "todo" },
        }[tier] ?? { emoji: "⚪", label: tier, cls: "" };
        const scenarios = Array.isArray(step.scenarios) ? step.scenarios : [];
        const showScenarios = tier !== "GREAT" && scenarios.length > 0;
        const signals = Array.isArray(step.signals) ? step.signals : [];
        const hasUrl = !!step.setup_url;
        const external = !!step.setup_url_external;
        // v1.2.15: setup URL is shown at every tier — including GREAT —
        // so users can verify or revisit the underlying config (Companion
        // App page, /config/devices etc). Pre-v1.2.15 the link was hidden
        // when tier === "GREAT", leaving the user with "Working great" and
        // no way to inspect WHAT was working. Same URL, different
        // call-to-action verb per tier.
        const linkVerb = tier === "GREAT" ? "Manage" : (step.setup_url_label ?? "Set this up");
        return b `
      <div class="setup-step setup-step--${tierBadge.cls}">
        <div class="setup-step-header">
          <span class="setup-step-tier">
            ${tierBadge.emoji} ${tierBadge.label}
          </span>
          <span class="setup-step-name">${step.feature ?? ""}</span>
        </div>
        ${step.advice
            ? b `<div class="setup-step-advice">${step.advice}</div>`
            : A}
        ${signals.length > 0
            ? b `
              <details class="setup-step-signals" ?open=${tier === "GREAT"}>
                <summary>Detected signals (${signals.length})</summary>
                <ul>
                  ${signals.map((s) => b `<li>${s}</li>`)}
                </ul>
              </details>
            `
            : A}
        ${showScenarios
            ? b `
              <details class="setup-step-scenarios">
                <summary>What this unlocks</summary>
                <ul>
                  ${scenarios.map((s) => b `<li>${s}</li>`)}
                </ul>
              </details>
            `
            : A}
        ${hasUrl
            ? external
                ? b `
                <div class="setup-step-action">
                  <a
                    class="action ${tier === "GREAT" ? "" : "primary"}"
                    href=${step.setup_url}
                    target="_blank"
                    rel="noopener"
                  >${linkVerb} ↗</a>
                </div>
              `
                : b `
                <div class="setup-step-action">
                  <a
                    class="action ${tier === "GREAT" ? "" : "primary"}"
                    href=${step.setup_url}
                  >${linkVerb} →</a>
                </div>
              `
            : tier !== "GREAT" && step.next_step
                ? b `<div class="setup-step-note">${step.next_step}</div>`
                : A}
        ${tier !== "GREAT" && step.feature_key === "presence_inference"
            ? b `
              <div class="setup-step-action">
                <button
                  class="action"
                  title="Open a bulk area-assignment dialog inside HA Insights — no leaving the panel"
                  @click=${() => {
                this._bulkAreaAssignOpen = true;
            }}
                >📍 Bulk assign in HA Insights</button>
              </div>
            `
            : A}
      </div>
    `;
    }
    _renderDialog() {
        if (!this._dialogId)
            return A;
        const insight = this._insights.find((i) => i.id === this._dialogId);
        if (!insight)
            return A;
        const busy = this._busyId === insight.id;
        const llmEnabled = this._hello?.privacy_mode && this._hello.privacy_mode !== "off";
        const ttsConfigured = Boolean(this._config.tts_target_entity_id);
        const confidencePct = Math.round(insight.confidence * 100);
        const refined = this._refinedById.get(insight.id);
        return b `
      <div class="dialog-backdrop" @click=${this._closeDialog}>
        <div class="dialog" @click=${(e) => e.stopPropagation()}>
          <div class="dialog-header">
            <div class="dialog-title">
              ${this._displayTitle(insight)}
              ${this._renderCouplingBadge(insight)}
              ${this._renderDirectionalityBadge(insight)}
              ${this._renderEntityAgeBadge(insight)}
            </div>
            <button
              class="dialog-close"
              aria-label="Close"
              @click=${this._closeDialog}
            >×</button>
          </div>
          ${refined
            ? b `<div class="dialog-body">
                ${this._renderModalError()}
                ${this._renderTestResults()}
                ${this._renderRefinedPreview(insight, refined)}
              </div>`
            : insight.detector === "setup_quality"
                ? this._renderSetupGuideBody(insight)
                : insight.detector === "automation_audit"
                    && insight.payload_format !== "automation"
                    ? this._renderAuditBody(insight)
                    : this._hasSpecializedCardRenderer(insight)
                        ? this._renderCardBody(insight)
                        : b `
                <div class="dialog-body">
                  ${this._renderModalError()}
                  ${this._renderTestResults()}
                  <div class="row-meta">
                    <span class="pill">confidence ${confidencePct}%</span>
                    <span class="pill">${insight.detector}</span>
                    ${insight.area_id ? b `<span class="pill">${insight.area_id}</span>` : A}
                    ${insight.conflicts_with.length > 0
                            ? b `<span class="pill" style="color: var(--warning-color)">conflicts</span>`
                            : A}
                  </div>
                  <h4>${this._payloadHeading(insight.payload_format)}</h4>
                  ${this._renderPayloadView(insight)}
                  ${insight.explanation
                            ? b `<div class="explanation">${insight.explanation}</div>`
                            : A}
                  ${this._hypothesisById.has(insight.id)
                            ? b `<div class="explanation hypothesis">
                        <strong>Likely causes:</strong>
                        ${this._hypothesisById.get(insight.id)}
                      </div>`
                            : A}
                  ${this._renderManagedDevicesSection(insight)}
                  ${this._renderPreview(insight)}
                  ${this._renderRename(insight, undefined)}
                  ${llmEnabled
                            ? this._renderFeedbackInput(insight, "Notes for the LLM (optional, used by Refine)")
                            : A}
                  <div class="explain-row">
                    ${llmEnabled && !insight.explanation
                            ? b `
                          <button
                            class="action ${this._explainBusy ? "busy-pulse" : ""}"
                            ?disabled=${this._explainBusy}
                            @click=${() => this._explain(insight)}
                          >
                            ${this._explainBusy ? "💭 thinking…" : "Explain with LLM"}
                          </button>
                        `
                            : A}
                    ${llmEnabled && insight.payload_format === "automation"
                            ? b `
                          <button
                            class="action ${this._refineBusy ? "busy-pulse" : ""}"
                            ?disabled=${this._refineBusy}
                            title="${this._refineConversationById.has(insight.id)
                                ? "Continue the LLM conversation with new feedback"
                                : "Ask the LLM to refine this automation"}"
                            @click=${() => this._refine(insight)}
                          >
                            ${this._refineBusy
                                ? "💭 refining…"
                                : this._refineConversationById.has(insight.id)
                                    ? `✨ Refine again (turn ${(this._refineTurnsById.get(insight.id) ?? 0) + 1})`
                                    : "✨ Refine with LLM"}
                          </button>
                          ${this._refineConversationById.has(insight.id)
                                ? b `<button
                                class="action"
                                title="Forget the prior conversation and start a fresh refine thread"
                                @click=${() => {
                                    this._resetRefineConversation(insight.id);
                                    this._toast = "Refine conversation reset";
                                }}
                              >
                                🔁 Reset conversation
                              </button>`
                                : A}
                        `
                            : A}
                    ${llmEnabled
                            ? b `
                          <button
                            class="action"
                            ?disabled=${this._previewBusy}
                            title="Preview the exact data that would be sent to the LLM"
                            @click=${() => this._previewRedaction(insight)}
                          >
                            ${this._previewBusy
                                ? "loading…"
                                : this._previewById.has(insight.id)
                                    ? "🛡️ Hide preview"
                                    : "🛡️ What gets sent?"}
                          </button>
                        `
                            : A}
                    ${llmEnabled && insight.kind === "anomaly"
                            ? b `
                          <button
                            class="action ${this._hypothesizeBusy ? "busy-pulse" : ""}"
                            ?disabled=${this._hypothesizeBusy}
                            title="Ask the LLM for plausible causes of this anomaly"
                            @click=${() => this._hypothesize(insight)}
                          >
                            ${this._hypothesizeBusy
                                ? "💭 thinking…"
                                : this._hypothesisById.has(insight.id)
                                    ? "🔍 Re-hypothesize"
                                    : "🔍 Get hypothesis"}
                          </button>
                        `
                            : A}
                    ${ttsConfigured && insight.explanation
                            ? b `
                          <button
                            class="action"
                            ?disabled=${this._ttsBusy}
                            title="Read aloud on ${this._config.tts_target_entity_id}"
                            @click=${() => this._readAloud(insight)}
                          >
                            ${this._ttsBusy ? "speaking…" : "🔊 Read aloud"}
                          </button>
                        `
                            : A}
                    ${insight.payload_format === "automation"
                            ? b `<button
                          class="action"
                          ?disabled=${this._testBusy}
                          title="Fire the action(s) for real"
                          @click=${() => this._testActions(insight)}
                        >
                          ${this._testBusy ? "testing…" : "🔥 Test actions"}
                        </button>`
                            : A}
                    ${this._primaryEntityId(insight) !== null
                            ? b `<button
                          class="action"
                          title="Find My iPhone style: opens a modal that fires the entity's native identifier (light flash / chime / fan flicker) every 5 seconds until you click 'Found it!'. Multi-entity insights show every referenced entity as a checkbox so you can identify them one at a time."
                          @click=${() => this._identifyEntity(insight)}
                        >
                          🔆 Identify entity
                        </button>
                        <button
                          class="action"
                          title="Live RSSI from the entity's BLE advertisements. Walk around with your phone — the trend arrow tells you whether you're getting closer or further. EXPERIMENTAL — requires the entity to be BLE-trackable (companion app or a BLE proxy)."
                          @click=${() => this._openBleFindForInsight(insight)}
                        >
                          📡 BLE find
                        </button>`
                            : A}
                  </div>
                  ${!llmEnabled
                            ? b `<div class="subtitle" style="margin-top: 12px;">
                        LLM Explain / Refine disabled — enable Local or Cloud mode in
                        Settings → Devices & Services.
                      </div>`
                            : A}
                </div>
                <div class="dialog-footer">
                  <button class="action" ?disabled=${busy} @click=${() => this._dismiss(insight)}>
                    Dismiss
                  </button>
                  ${insight.applied_at
                            ? A
                            : b `<button
                        class="action"
                        ?disabled=${busy}
                        @click=${() => this._snooze(insight)}
                      >
                        Snooze 7d
                      </button>`}
                  ${insight.applied_at || insight.retired_at
                            ? A
                            : b `<button
                        class="action retire"
                        ?disabled=${busy}
                        title="Permanently retire this suggestion — won't appear again unless un-retired from the history view"
                        @click=${() => this._retire(insight)}
                      >
                        Retire
                      </button>`}
                  ${insight.retired_at
                            ? b `<button
                        class="action"
                        ?disabled=${busy}
                        title="Reverse the retire decision — this insight goes back into the active queue"
                        @click=${() => this._unretire(insight)}
                      >
                        ↺ Un-retire
                      </button>`
                            : A}
                  ${insight.applied_at
                            ? b `<button
                        class="action primary"
                        ?disabled=${busy}
                        title="Remove the automation and revert this insight to active"
                        @click=${() => this._undo(insight)}
                      >
                        ${busy ? "undoing…" : "↶ Undo apply"}
                      </button>`
                            : insight.payload_format === "automation"
                                ? b `<button
                          class="action primary"
                          ?disabled=${busy}
                          @click=${() => this._apply(insight)}
                        >
                          ${busy ? "applying…" : "Apply"}
                        </button>`
                                : A}
                </div>
              `}
        </div>
      </div>
    `;
    }
    _renderErrorBanner() {
        if (!this._error)
            return A;
        return b `
      <div class="error-banner">
        <span>${this._error}</span>
        <button @click=${() => (this._error = undefined)}>Dismiss</button>
      </div>
    `;
    }
    render() {
        // v1.2.9: no "Loading…" curtain. The card renders based on data
        // it actually has — insights (the real payload), _hello (server
        // contact), _error (visible failure), _scanInProgress (transient).
        // Empty data + no contact yet = the normal empty state below
        // with a Refresh CTA, NOT a stuck "Loading…" screen.
        //
        // Scan-in-progress curtain. Hides the live-mutating subscribe stream
        // until the canonical post-scan ws_list lands via _refreshFromEvent.
        // Header stays visible so the user has context + can still click the
        // Stop button or other controls.
        if (this._scanInProgress) {
            return b `
        <ha-card>
          ${this._renderHeader()}
          <div class="empty empty-scanning">
            <div class="spinner" aria-hidden="true"></div>
            <div>Scanning…</div>
            <div class="empty-sub">
              Running detectors. Results appear when the scan finishes.
            </div>
          </div>
        </ha-card>
      `;
        }
        const rows = this._filtered();
        if (this._config.compact) {
            return b `
        <ha-card>
          ${this._renderSkewBanner()}
          ${this._renderErrorBanner()}
          ${this._renderCompactTile(rows)}
        </ha-card>
      `;
        }
        return b `
      <ha-card>
        ${this._renderHeader()}
        ${this._renderSkewBanner()}
        ${this._renderErrorBanner()}
        ${this._toast ? b `<div class="toast">${this._toast}</div>` : A}
        ${rows.length === 0
            ? b `<div class="empty">
              <div>Watching your home. New insights appear here as patterns emerge.</div>
              <div class="empty-actions">
                <button
                  ?disabled=${this._scanBusy}
                  @click=${this._runScanNow}
                  title="Run all detectors against the current state buffer"
                >
                  ${this._scanBusy ? "Scanning…" : "🔍 Run scan now"}
                </button>
                <a
                  href="https://github.com/botts7/ha-insights"
                  target="_blank"
                  rel="noopener"
                  title="Open the project README"
                >
                  How it works ↗
                </a>
              </div>
            </div>`
            : this._grouped(rows).flatMap(([key, items]) => key
                ? [
                    b `<div class="group-header">${key} (${items.length})</div>`,
                    ...items.map((i) => this._renderRow(i)),
                ]
                : items.map((i) => this._renderRow(i)))}
        ${this._renderTruncationFooter(rows.length)}
      </ha-card>
      ${this._renderDialog()}
      ${this._renderBleFindModal()}
      ${this._renderIdentifyModal()}
      ${this._renderRefineAutomationModal()}
      ${this._renderSuggestAddDialog()}
      <bulk-area-assign-dialog
        .hass=${this.hass}
        ?open=${this._bulkAreaAssignOpen}
        @closed=${() => {
            this._bulkAreaAssignOpen = false;
        }}
        @assignments-saved=${(e) => {
            const detail = e.detail;
            this._toast = `Areas saved: ${detail.saved}${detail.failed ? ` (${detail.failed} failed)` : ""}`;
        }}
      ></bulk-area-assign-dialog>
    `;
    }
    /** v1.2.3 — Footer that says "Showing N of M — +X more → View all".
     *  Only appears when the dashboard tile is sized to show fewer rows
     *  than the user actually has. Without it the tile shows 1 insight
     *  with no hint that 25 more are queued behind "View all" in the
     *  header. */
    _renderTruncationFooter(rendered) {
        const total = this._totalFilteredCount;
        if (total <= rendered)
            return A;
        const hidden = total - rendered;
        return b `
      <a class="truncation-footer" href="/ha-insights" title="Open the full HA Insights panel">
        Showing ${rendered} of ${total} — +${hidden} more →
      </a>
    `;
    }
}
__decorate([
    n({ attribute: false })
], HaInsightsCard.prototype, "hass", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_config", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_hello", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_insights", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_error", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_modalError", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_scanInProgress", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_busyId", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_toast", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_dialogId", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_explainBusy", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_auditSuggestBusy", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_suggestAddBusy", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_suggestAddDialog", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_ttsBusy", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_showHistory", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_refineBusy", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_hypothesisById", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_hypothesizeBusy", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_refineConversationById", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_refineTurnsById", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_testBusy", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_scanBusy", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_refinedById", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_renameEdits", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_feedbackById", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_payloadEditsById", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_editingPayloadFor", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_payloadParseErrorById", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_previewById", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_previewBusy", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_identifyBusy", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_identifyOpen", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_identifyEntityId", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_identifyMethod", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_identifyCount", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_identifyError", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_identifySelected", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_identifyAllEntities", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_identifyOneAtATime", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_bleFindOpen", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_bleFindEntity", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_bleFindAddress", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_bleFindLatest", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_bleTrendBuffer", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_bleFindError", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_testResults", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_expandedCohorts", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_refineAutomationModal", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_bulkAreaAssignOpen", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_autoMaxRows", void 0);
__decorate([
    r()
], HaInsightsCard.prototype, "_totalFilteredCount", void 0);
// Guard against double-registration: ha-insights-card.js and
// ha-insights-panel.js both ship this class (panel imports card to
// embed it). When the user has the card resource loaded AND the
// integration auto-registers the panel JS, both bundles try to
// define("ha-insights-card") and the second throws. The .get() check
// makes the second load a no-op.
if (!customElements.get("ha-insights-card")) {
    customElements.define("ha-insights-card", HaInsightsCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "ha-insights-card")) {
    window.customCards.push({
        type: "ha-insights-card",
        name: "HA Insights Card",
        description: "Shows insights from the HA Insights integration",
    });
}

// v1.3.4: register a panel-bundled alias of the card so the panel
// ALWAYS uses the version of HaInsightsCard built INTO this bundle —
// never the (possibly stale) HACS-installed `ha-insights-card` whose
// class registered first and won the `ha-insights-card` name.
//
// Real-install diagnostic on 2026-05-17 confirmed: card v1.3.0+
// added the 🔗 coupling badge to _renderRow, but users on the side
// panel never saw it because the HACS-loaded card (registered first)
// owned the `ha-insights-card` element name. The panel embedded that
// stale class. customElements doesn't allow re-defining a name once
// taken, so the fresh bundled class was silently discarded.
//
// Solution: panel uses `ha-insights-card-bundled`, registered as a
// trivial subclass of the freshly-built HaInsightsCard from this
// bundle. Always current with the integration's panel.js, regardless
// of what HACS has done with the dashboard card.
const PANEL_CARD_TAG = "ha-insights-card-bundled";
/** Domains whose entities can be physically identified — must stay
 *  aligned with `lib/identify_capability.py::identify_capability_for`.
 *  Listing software-only domains (automation, scene, script, calendar,
 *  sensor, etc.) in the Find-Device modal frustrates the user because
 *  the backend returns NONE and the loop reports "no identify method
 *  available". Filter at the source instead. */
const FINDABLE_DOMAINS = new Set([
    "light",
    "switch",
    "media_player",
    "siren",
]);
/** Sensor device_classes that respond to deliberate physical
 *  perturbation. Must stay aligned with the keys of
 *  `lib/perturbation_capability.py::_GUIDES`. Touching, breathing
 *  on, or covering one of these sensors produces a state spike
 *  large enough to fingerprint it against siblings. */
const PERTURBABLE_DEVICE_CLASSES = new Set([
    "temperature",
    "humidity",
    "carbon_dioxide",
    "illuminance",
    "sound_pressure",
    "moisture",
]);
/** Per-device_class state-delta threshold that counts as a
 *  "detected" spike (touch was you, not ambient drift). Mirrors
 *  `perturbation_capability.py::PerturbationGuide.expected_delta`
 *  scaled down to ~0.5× so a genuine touch reliably exceeds it
 *  but ambient noise doesn't. Used by the Find Device sensor-watch
 *  mode for inline detection without round-tripping to the
 *  perturbation_test WS endpoint. */
const PERTURBATION_DETECTION_THRESHOLDS = {
    temperature: 1.0, // °C
    humidity: 5.0, // %RH
    carbon_dioxide: 200.0, // ppm
    illuminance: 100.0, // lx
    sound_pressure: 10.0, // dB
    moisture: 50.0, // %
};
/** Binary-sensor device_classes you can "walk and watch" — wave at
 *  a motion sensor, walk past an occupancy sensor, open a contact
 *  — and the entity flips off→on right then. Card subscribes to
 *  state changes and highlights the first off→on transition. */
const WATCHABLE_BINARY_DEVICE_CLASSES = new Set([
    "motion",
    "occupancy",
    "presence",
    "opening",
    "door",
    "window",
    "vibration",
]);
/** Per-domain loop cadence for the panel-level Find Device modal.
 *  Tuned so total fire rate over a long search session looks like
 *  a curious human poking, not a robotic loop. Switches especially
 *  must be slow — many smart-light vendors interpret rapid on/off
 *  cycles as factory-reset triggers (Tuya: 3× in 10 s; Aqara: 5× in
 *  5 s; Hue: 5× in 10 s). Even though the per-fire pattern stays
 *  under those thresholds, looping a 2-toggle burst every 5 s
 *  aggregates to 240+ toggles over 10 minutes — relay-killing and
 *  log-noise. Per-domain cadence keeps the AGGREGATE rate sane. */
const FIND_DEVICE_CADENCE_MS = {
    light: 5000,
    media_player: 6000,
    siren: 10000,
    switch: 12000,
};
const FIND_DEVICE_DEFAULT_CADENCE_MS = 5000;
/** Hard safety ceiling on a Find Device session. After this elapses
 *  the loop auto-stops with a toast — covers the case where the
 *  user forgets the modal is open or leaves the tab. 5 minutes is
 *  long enough for any honest search (walk every room) but short
 *  enough that an abandoned session can't accumulate hundreds of
 *  toggles unattended. */
const FIND_DEVICE_MAX_SESSION_MS = 5 * 60 * 1000;
/** Max fires per individual entity before that entity auto-stops
 *  (the rest of the selection keeps going). At 12 s switch cadence
 *  this caps switches at 30 toggles total even if the user never
 *  unchecks them. */
const FIND_DEVICE_MAX_FIRES_PER_ENTITY = 30;
if (!customElements.get(PANEL_CARD_TAG)) {
    customElements.define(PANEL_CARD_TAG, class extends HaInsightsCard {
    });
}
class HaInsightsPanel extends i {
    constructor() {
        super(...arguments);
        this.narrow = false;
        this._search = "";
        this._minConfidence = 0;
        this._sortBy = "confidence";
        this._groupBy = "none";
        // v1.5.30: panel-side toggle for shadowed insights. We deliberately
        // do NOT suppress these at scan time (a 1000-entity install reported
        // 0 insights when we did — see detectors/__init__.py history-rich
        // comment). The badge tells the user "HA noticed, you already did
        // it"; this toggle lets a power user collapse those rows when they
        // want to focus on net-new patterns. Default OFF (current behavior).
        this._hideAlreadyAutomated = false;
        this._backfillBusy = false;
        this._bulkBusy = false;
        this._scanBusy = false;
        this._rollupBusy = false;
        this._rollupProgress = null;
        this._rollupPollTimer = null;
        this._recorderStatus = null;
        // v1.1 panel filters — chip-style multi-select. Empty array = no filter.
        // Persisted alongside search/confidence/sort in localStorage.
        this._filterDomains = [];
        this._filterAreas = [];
        this._filterDeviceClasses = [];
        this._filterDetectors = [];
        // v1.2 Phase 5: floor + integration axes alongside domain/area/dc/detector.
        this._filterFloors = [];
        this._filterIntegrations = [];
        // v1.5.28: labels (HA 2024.4+) — user-applied tags that cascade
        // from entity → device → area. A user with `label: outdoor`,
        // `label: critical`, etc. can slice insights by their own taxonomy.
        this._filterLabels = [];
        // v1.2.1: depth of LLM reasoning for 🤖 Suggest. "concise" is the
        // cheap default (~150 token rules); "indepth" sends a fuller
        // protocol (~600 token rules) for tricky cases. Persists across
        // page loads. Passed through the embedded card config.
        this._auditDepth = "concise";
        // Total insight count BEFORE chip filters. The card returns the
        // post-filter count via a property; we maintain the pre-filter count
        // here for the "Showing X of Y" hint in the panel header.
        this._totalInsightCount = 0;
        this._visibleInsightCount = 0;
        // v1.10.4 — diagnostics modal (calls home_insights/export_dev_audit
        // via WS, shows redacted JSON for bug reports + LLM-driven
        // verification). The modal is open when _diagnosticsJson is set;
        // _diagnosticsBusy gates the button while the WS call is in flight.
        this._diagnosticsJson = null;
        this._diagnosticsBusy = false;
        // v1.10.8 — Find My HA Device feature. Top-level entity picker +
        // looping identifier. Users open from the panel header to locate
        // ANY entity (not just ones surfaced in insights). Same backend as
        // the per-insight 🔆 Identify (home_insights/identify_entity);
        // different entry point. Search box filters live by entity_id /
        // friendly_name; selected entities are added to a "currently
        // identifying" set; loop fires identify on every selected entity
        // every 5s until user clicks "Found them all" / "Stop".
        this._findDeviceOpen = false;
        this._findDeviceSearch = "";
        this._findDeviceSelected = new Set();
        this._findDeviceCount = 0;
        this._findDeviceErrors = {};
        this._findDeviceTimer = null;
        // Safety ceilings — both the panel-wide elapsed time and the
        // per-entity fire count are gated so an abandoned session can't
        // accumulate hundreds of toggles. See FIND_DEVICE_MAX_SESSION_MS
        // and FIND_DEVICE_MAX_FIRES_PER_ENTITY constants.
        this._findDeviceSessionStartedAt = 0;
        this._findDeviceFireCounts = {};
        this._findDeviceSessionElapsedMs = 0;
        // Per-entity user acknowledgement that they UNDERSTAND this entity
        // will be power-cycled (switch toggle / strobe / siren chirp). The
        // backend WS handler refuses to fire power-cycle methods until the
        // card sends confirm_power_cycle=true. Once the user confirms once,
        // we remember it for the duration of the modal session.
        this._findDevicePowerCycleConfirmed = new Set();
        // Snapshot of distinct values present in the loaded insight set.
        // Drives the chip dropdown options. Refreshed on every list reload.
        this._availableDomains = [];
        this._availableAreas = [];
        this._availableDeviceClasses = [];
        this._availableDetectors = [];
        // v1.2 Phase 5
        this._availableFloors = [];
        this._availableIntegrations = [];
        // v1.5.28: distinct labels across the loaded insight set.
        this._availableLabels = [];
        // Area-id ↔ display-name maps populated from the loaded insight set
        // so chip dropdowns and the per-detector header show friendly labels
        // ("Living Room") instead of opaque registry ids.
        this._areaNameById = {};
        this._floorNameById = {};
        // Per-detector counts displayed as small chips in the header.
        // Populated from the SAME insight set as the filter chip dropdowns.
        this._detectorCounts = {};
        this._toast = "";
        this._auditOpen = false;
        this._auditLog = [];
        this._auditBusy = false;
        this._onInsightsLoaded = (e) => {
            const detail = e.detail;
            const insights = detail?.insights ?? [];
            this._totalInsightCount = insights.length;
            // Distinct values populate chip dropdowns. Sorted for stable UI.
            this._availableDomains = [
                ...new Set(insights.map((i) => i.domain).filter((v) => !!v)),
            ].sort();
            this._availableAreas = [
                ...new Set(insights.map((i) => i.area_id).filter((v) => !!v)),
            ].sort();
            this._availableDeviceClasses = [
                ...new Set(insights.map((i) => i.device_class).filter((v) => !!v)),
            ].sort();
            this._availableDetectors = [
                ...new Set(insights.map((i) => i.detector).filter((v) => !!v)),
            ].sort();
            this._availableFloors = [
                ...new Set(insights.map((i) => i.floor_id).filter((v) => !!v)),
            ].sort();
            this._availableIntegrations = [
                ...new Set(insights.map((i) => i.integration).filter((v) => !!v)),
            ].sort();
            // v1.5.28: distinct labels across insights. Each insight can
            // carry multiple labels (entity + device + area cascade); flatten
            // into a single set.
            this._availableLabels = [
                ...new Set(insights.flatMap((i) => Array.isArray(i.labels)
                    ? (i.labels)
                    : [])),
            ].sort();
            // Build id → friendly-name lookups from the loaded list. The card
            // already carries area_name + floor_name on each row when set;
            // collecting them here keeps chip labels readable.
            const areaNames = {};
            const floorNames = {};
            for (const i of insights) {
                if (typeof i.area_id === "string" && typeof i.area_name === "string") {
                    areaNames[i.area_id] = i.area_name;
                }
                if (typeof i.floor_id === "string" && typeof i.floor_name === "string") {
                    floorNames[i.floor_id] = i.floor_name;
                }
            }
            this._areaNameById = areaNames;
            this._floorNameById = floorNames;
            // Per-detector counts for the header chip strip.
            const counts = {};
            for (const i of insights) {
                const d = i.detector;
                if (typeof d === "string")
                    counts[d] = (counts[d] ?? 0) + 1;
            }
            this._detectorCounts = counts;
            // Compute visible count by re-applying the same filter the card uses
            // (search + min_confidence + chip filters). Cheap; same N as card.
            const search = this._search.trim().toLowerCase();
            const dom = new Set(this._filterDomains);
            const area = new Set(this._filterAreas);
            const dc = new Set(this._filterDeviceClasses);
            const det = new Set(this._filterDetectors);
            const floor = new Set(this._filterFloors);
            const integ = new Set(this._filterIntegrations);
            this._visibleInsightCount = insights.filter((i) => {
                const conf = i.confidence ?? 0;
                if (conf < this._minConfidence)
                    return false;
                const title = (i.title ?? "").toLowerCase();
                if (search && !title.includes(search))
                    return false;
                if (dom.size > 0 && !(typeof i.domain === "string" && dom.has(i.domain)))
                    return false;
                if (area.size > 0 && !(typeof i.area_id === "string" && area.has(i.area_id)))
                    return false;
                if (dc.size > 0 && !(typeof i.device_class === "string" && dc.has(i.device_class)))
                    return false;
                if (det.size > 0 && !(typeof i.detector === "string" && det.has(i.detector)))
                    return false;
                if (floor.size > 0 && !(typeof i.floor_id === "string" && floor.has(i.floor_id)))
                    return false;
                if (integ.size > 0 &&
                    !(typeof i.integration === "string" && integ.has(i.integration))) {
                    return false;
                }
                return true;
            }).length;
        };
        this._rollupLoopAborted = false;
        this._rollupLoopStartTs = 0;
        /** Timer tick. Runs at 1 s cadence; per-entity cadence is enforced
         *  by checking the entity's last-fire time against its
         *  domain-specific FIND_DEVICE_CADENCE_MS. Hard ceilings auto-stop
         *  individual entities (FIND_DEVICE_MAX_FIRES_PER_ENTITY) and the
         *  whole session (FIND_DEVICE_MAX_SESSION_MS). */
        this._findDeviceLastFiredAt = {};
        // v1.10.10 — Passive-sensor watch mode. When the user checks a
        // perturbable sensor (temp / humidity / CO₂ / illuminance / etc.)
        // or a motion / occupancy binary_sensor, we don't fire identify —
        // we subscribe to state changes and watch for a delta (sensors) or
        // off→on transition (binary_sensors). Baseline is captured at
        // first subscription; threshold values from PERTURBATION_DETECTION_THRESHOLDS.
        this._findDeviceWatchUnsubs = new Map();
        this._findDeviceWatchBaselines = {};
        this._findDeviceWatchCurrent = {};
        this._findDeviceWatchDetected = new Set();
    }
    // Persistent filter storage (v0.8 phase 6). Versioned key so future
    // shape changes can ignore old saved state cleanly.
    static { this._STORAGE_KEY = "ha-insights-panel-filters-v1"; }
    // Schema version embedded INSIDE the stored JSON. Bump when adding /
    // removing / renaming filter state fields. On mismatch we silently
    // discard and start fresh — avoids carrying ghost lists from earlier
    // versions of the panel into a release where the field shape changed.
    static { this._STORAGE_SCHEMA_VERSION = 2; }
    static { this.styles = i$3 `
    :host {
      display: block;
      box-sizing: border-box;
      min-height: 100vh;
      background: var(--primary-background-color, #f6f7f9);
      color: var(--primary-text-color);
    }
    .header {
      padding: 18px 24px 12px;
      background: var(--app-header-background-color, var(--card-background-color, white));
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
      position: sticky;
      top: 0;
      z-index: 4;
      display: flex;
      align-items: flex-start;
      gap: 16px;
    }
    .header .titles {
      flex: 1;
    }
    .header h1 {
      margin: 0 0 4px;
      font-size: 1.6em;
      font-weight: 500;
    }
    .header .sub {
      font-size: 0.9em;
      color: var(--secondary-text-color);
    }
    .header .actions {
      display: flex;
      gap: 8px;
      flex-shrink: 0;
    }
    .header button.action {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: none;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.18));
      padding: 8px 14px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.9em;
      color: var(--primary-text-color);
    }
    .header button.action ha-icon {
      --mdc-icon-size: 18px;
      width: 18px;
      height: 18px;
      color: var(--secondary-text-color);
    }
    .header button.action.primary {
      background: var(--primary-color, #4c6ef5);
      border-color: var(--primary-color, #4c6ef5);
      color: var(--text-primary-color, #fff);
      font-weight: 500;
    }
    .header button.action.primary ha-icon {
      color: var(--text-primary-color, #fff);
    }
    .header button.action:hover:not(:disabled) {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
    }
    .header button.action.primary:hover:not(:disabled) {
      filter: brightness(1.08);
      background: var(--primary-color, #4c6ef5);
    }
    .header button.action:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .toast {
      position: fixed;
      top: 16px;
      right: 16px;
      background: var(--success-color, #4caf50);
      color: white;
      padding: 10px 14px;
      border-radius: 6px;
      font-size: 0.9em;
      z-index: 10;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }
    /* v1.10.4: diagnostics modal */
    .diagnostics-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.45);
      z-index: 20;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }
    .diagnostics-dialog {
      background: var(--card-background-color, white);
      color: var(--primary-text-color, #212121);
      border-radius: 8px;
      width: min(900px, 100%);
      max-height: 85vh;
      display: flex;
      flex-direction: column;
      box-shadow: 0 12px 36px rgba(0, 0, 0, 0.35);
    }
    .diagnostics-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 18px;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
    }
    .diagnostics-close {
      background: none;
      border: none;
      font-size: 1.5em;
      cursor: pointer;
      color: var(--primary-text-color);
      line-height: 1;
    }
    .diagnostics-body {
      padding: 14px 18px;
      overflow: auto;
      flex: 1 1 auto;
    }
    .diagnostics-hint {
      margin: 0 0 12px 0;
      font-size: 0.9em;
      color: var(--secondary-text-color);
    }
    .diagnostics-json {
      background: var(--code-editor-background-color, rgba(0, 0, 0, 0.04));
      color: var(--primary-text-color);
      padding: 12px;
      border-radius: 4px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.85em;
      overflow: auto;
      max-height: 50vh;
      white-space: pre;
    }
    .diagnostics-actions {
      display: flex;
      gap: 8px;
      padding: 12px 18px;
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
      justify-content: flex-end;
    }
    /* v1.10.8: Find My HA Device modal */
    .find-device-dialog { width: min(720px, 100%); }
    .find-device-search {
      width: 100%;
      box-sizing: border-box;
      padding: 8px 10px;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.12));
      border-radius: 6px;
      font-size: 0.95em;
      margin-bottom: 8px;
    }
    .find-device-status {
      font-size: 0.85em;
      color: var(--secondary-text-color);
      margin-bottom: 8px;
    }
    .find-device-list {
      max-height: 360px;
      overflow-y: auto;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
      border-radius: 6px;
    }
    .find-device-empty {
      padding: 18px;
      text-align: center;
      color: var(--secondary-text-color);
      font-size: 0.9em;
    }
    .find-device-row {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      padding: 6px 10px;
      cursor: pointer;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.04));
    }
    .find-device-row:hover {
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
    }
    .find-device-row:last-child { border-bottom: none; }
    .find-device-row-text {
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      min-width: 0;
    }
    .find-device-eid {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.88em;
      color: var(--primary-text-color);
    }
    .find-device-name {
      font-size: 0.85em;
      color: var(--secondary-text-color);
    }
    .find-device-err {
      font-size: 0.8em;
      color: var(--warning-color, #ef6c00);
      margin-top: 2px;
    }
    .find-device-fires {
      font-size: 0.78em;
      color: var(--secondary-text-color);
      margin-top: 2px;
    }
    .find-device-watch-hint {
      font-size: 0.8em;
      color: var(--secondary-text-color);
      margin-top: 4px;
      padding: 4px 8px;
      border-left: 2px solid var(--info-color, #3b82f6);
      background: rgba(59, 130, 246, 0.06);
      border-radius: 2px;
    }
    .find-device-row--perturb .find-device-eid::before,
    .find-device-row--watch .find-device-eid::before {
      /* Emoji icons supplied inline in the template — no extra CSS
         pseudo-content needed; keep the selector for potential
         future per-mode styling. */
    }
    .find-device-row--detected {
      background: rgba(76, 175, 80, 0.08);
      border-left: 3px solid var(--success-color, #4caf50);
    }
    .find-device-truncated {
      padding: 8px;
      font-size: 0.82em;
      color: var(--secondary-text-color);
      text-align: center;
    }
    .filters {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      padding: 12px 24px;
      background: var(--card-background-color, white);
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
      align-items: center;
    }
    .filters input[type="search"] {
      flex: 1 1 280px;
      padding: 8px 12px;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.18));
      border-radius: 6px;
      font: inherit;
      background: var(--card-background-color, white);
      color: var(--primary-text-color);
    }
    .filters input[type="search"]:focus {
      outline: none;
      border-color: var(--primary-color);
    }
    .filters .conf {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 0.9em;
      color: var(--secondary-text-color);
    }
    .filters input[type="range"] {
      width: 140px;
    }
    .filters select {
      padding: 6px 10px;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.18));
      border-radius: 6px;
      font: inherit;
      background: var(--card-background-color, white);
      color: var(--primary-text-color);
    }
    .filters select:focus {
      outline: none;
      border-color: var(--primary-color);
    }
    .body {
      padding: 16px 24px 32px;
      max-width: 1100px;
      margin: 0 auto;
    }

    /* Audit log section */
    .audit {
      max-width: 1100px;
      margin: 8px auto 32px;
      padding: 12px 24px 16px;
      background: var(--card-background-color, white);
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.08));
      border-radius: 8px;
    }
    .audit-toggle {
      display: flex;
      justify-content: space-between;
      align-items: center;
      cursor: pointer;
      user-select: none;
    }
    .audit-toggle h3 {
      margin: 0;
      font-size: 1em;
      font-weight: 500;
    }
    .audit-toggle .arrow {
      transition: transform 200ms;
    }
    .audit-toggle.open .arrow {
      transform: rotate(90deg);
    }
    .audit-empty {
      color: var(--secondary-text-color);
      font-size: 0.9em;
      padding: 12px 0 0;
    }
    .audit-list {
      list-style: none;
      padding: 0;
      margin: 12px 0 0;
      max-height: 400px;
      overflow-y: auto;
    }
    .audit-list li {
      padding: 8px 0;
      border-bottom: 1px solid var(--divider-color, rgba(0, 0, 0, 0.06));
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 12px;
      align-items: center;
      font-size: 0.88em;
    }
    .audit-list li:last-child {
      border-bottom: none;
    }
    .audit-icon {
      width: 1em;
      text-align: center;
    }
    .audit-icon-ok { color: var(--success-color, #2e7d32); }
    .audit-icon-fail { color: var(--error-color, #c62828); }
    .audit-meta {
      color: var(--secondary-text-color);
      font-size: 0.8em;
      margin-top: 2px;
    }
    .audit-bytes {
      font-family: var(--code-font-family, monospace);
      color: var(--secondary-text-color);
      white-space: nowrap;
      font-size: 0.8em;
    }
    .detector-counts {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 8px;
    }
    .detector-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 3px 8px;
      border-radius: 999px;
      border: 1px solid var(--divider-color, rgba(0, 0, 0, 0.18));
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.04));
      color: var(--primary-text-color);
      font-size: 0.78em;
      cursor: pointer;
      font-family: inherit;
    }
    .detector-chip:hover {
      background: var(--divider-color, rgba(0, 0, 0, 0.08));
    }
    .detector-chip.is-active {
      background: var(--primary-color);
      color: var(--text-primary-color, white);
      border-color: var(--primary-color);
    }
    .detector-chip-count {
      background: rgba(0, 0, 0, 0.12);
      padding: 0 6px;
      border-radius: 999px;
      font-weight: 600;
      font-size: 0.85em;
    }
    .detector-chip.is-active .detector-chip-count {
      background: rgba(255, 255, 255, 0.25);
    }
    .rollup-row {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: 8px 16px;
      border-top: 1px solid var(--divider-color, rgba(0, 0, 0, 0.1));
      background: var(--secondary-background-color, rgba(0, 0, 0, 0.03));
      font-size: 0.85em;
    }
    .rollup-bar-wrap {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .rollup-bar {
      flex: 1 1 200px;
      min-width: 160px;
      height: 8px;
      background: var(--divider-color, rgba(0, 0, 0, 0.12));
      border-radius: 999px;
      overflow: hidden;
    }
    .rollup-bar-fill {
      height: 100%;
      transition: width 300ms ease-out;
      background: var(--primary-color);
    }
    .rollup-bar-fill.is-running {
      background: linear-gradient(
        90deg,
        var(--primary-color) 0%,
        var(--primary-color) 50%,
        rgba(255, 255, 255, 0.4) 100%
      );
      background-size: 200% 100%;
      animation: rollup-shimmer 1.6s linear infinite;
    }
    .rollup-bar-fill.is-done {
      background: var(--success-color, #4caf50);
    }
    @keyframes rollup-shimmer {
      from {
        background-position: 100% 0;
      }
      to {
        background-position: -100% 0;
      }
    }
    .rollup-stat {
      color: var(--secondary-text-color);
      white-space: nowrap;
    }
    .rollup-stat-done {
      color: var(--success-color, #4caf50);
    }
    .rollup-stat code {
      background: var(--divider-color, rgba(0, 0, 0, 0.08));
      padding: 1px 6px;
      border-radius: 4px;
      font-family: var(--code-font-family, "Roboto Mono", monospace);
      font-size: 0.9em;
    }
    .rollup-hint {
      color: var(--secondary-text-color);
      font-size: 0.9em;
    }
    .rollup-hint strong {
      color: var(--primary-text-color);
    }
    .rollup-hint-warn {
      color: var(--warning-color, #ff9800);
    }
    .rollup-hint-warn strong {
      color: var(--warning-color, #ff9800);
    }
    .rollup-hint-tip {
      margin-top: 4px;
      padding: 6px 8px;
      background: rgba(255, 152, 0, 0.08);
      border-left: 3px solid var(--warning-color, #ff9800);
      border-radius: 4px;
      font-size: 0.95em;
    }
    .rollup-hint-tip code {
      background: rgba(0, 0, 0, 0.08);
      padding: 1px 5px;
      border-radius: 3px;
      font-family: var(--code-font-family, "Roboto Mono", monospace);
    }
    @media (max-width: 600px) {
      .header,
      .filters,
      .body {
        padding-left: 12px;
        padding-right: 12px;
      }
    }
  `; }
    connectedCallback() {
        super.connectedCallback();
        this._loadFilters();
        // Bubble-listen for the embedded card's "insights-loaded" event so we
        // can refresh chip-filter options and the "Showing X of Y" counters
        // without owning the WS list call ourselves.
        this.addEventListener("insights-loaded", this._onInsightsLoaded);
        // One-shot recorder status read so the rollup section can show
        // the user's real available window without polling.
        void this._fetchRecorderStatus();
        // Cold-poll once in case a rollup is already running when the
        // panel mounts (e.g. user navigated away mid-batch and came back).
        void this._pollRollupProgress();
    }
    disconnectedCallback() {
        super.disconnectedCallback();
        this.removeEventListener("insights-loaded", this._onInsightsLoaded);
        this._stopRollupPoll();
    }
    updated() {
        // Save on any filter change. Cheap (<1 KB stringify) and synchronous.
        this._saveFilters();
    }
    _loadFilters() {
        try {
            const raw = window.localStorage.getItem(HaInsightsPanel._STORAGE_KEY);
            if (!raw)
                return;
            const saved = JSON.parse(raw);
            // Schema-version gate. Drop the saved state if it predates the
            // current schema — better to lose the user's filters than show
            // them stale data they can't see the shape of.
            if (saved.v !== HaInsightsPanel._STORAGE_SCHEMA_VERSION) {
                window.localStorage.removeItem(HaInsightsPanel._STORAGE_KEY);
                return;
            }
            if (typeof saved.search === "string")
                this._search = saved.search;
            if (typeof saved.minConfidence === "number") {
                this._minConfidence = saved.minConfidence;
            }
            if (saved.sortBy === "confidence" || saved.sortBy === "age" || saved.sortBy === "detector") {
                this._sortBy = saved.sortBy;
            }
            if (saved.groupBy === "none" ||
                saved.groupBy === "detector" ||
                saved.groupBy === "area" ||
                saved.groupBy === "floor" ||
                saved.groupBy === "integration" ||
                saved.groupBy === "label") {
                this._groupBy = saved.groupBy;
            }
            if (typeof saved.auditOpen === "boolean")
                this._auditOpen = saved.auditOpen;
            if (Array.isArray(saved.filterDomains)) {
                this._filterDomains = saved.filterDomains.filter((s) => typeof s === "string");
            }
            if (Array.isArray(saved.filterAreas)) {
                this._filterAreas = saved.filterAreas.filter((s) => typeof s === "string");
            }
            if (Array.isArray(saved.filterDeviceClasses)) {
                this._filterDeviceClasses = saved.filterDeviceClasses.filter((s) => typeof s === "string");
            }
            if (Array.isArray(saved.filterDetectors)) {
                this._filterDetectors = saved.filterDetectors.filter((s) => typeof s === "string");
            }
            if (Array.isArray(saved.filterFloors)) {
                this._filterFloors = saved.filterFloors.filter((s) => typeof s === "string");
            }
            if (Array.isArray(saved.filterIntegrations)) {
                this._filterIntegrations = saved.filterIntegrations.filter((s) => typeof s === "string");
            }
            // v1.5.28: load labels chip filter from localStorage
            if (Array.isArray(saved.filterLabels)) {
                this._filterLabels = saved.filterLabels.filter((s) => typeof s === "string");
            }
            // v1.5.30: hide-already-automated toggle
            if (typeof saved.hideAlreadyAutomated === "boolean") {
                this._hideAlreadyAutomated = saved.hideAlreadyAutomated;
            }
            if (saved.auditDepth === "concise" || saved.auditDepth === "indepth") {
                this._auditDepth = saved.auditDepth;
            }
        }
        catch {
            // Corrupted localStorage entry; fall back to defaults.
        }
    }
    _saveFilters() {
        try {
            window.localStorage.setItem(HaInsightsPanel._STORAGE_KEY, JSON.stringify({
                v: HaInsightsPanel._STORAGE_SCHEMA_VERSION,
                search: this._search,
                minConfidence: this._minConfidence,
                sortBy: this._sortBy,
                groupBy: this._groupBy,
                auditOpen: this._auditOpen,
                filterDomains: this._filterDomains,
                filterAreas: this._filterAreas,
                filterDeviceClasses: this._filterDeviceClasses,
                filterDetectors: this._filterDetectors,
                filterFloors: this._filterFloors,
                filterIntegrations: this._filterIntegrations,
                filterLabels: this._filterLabels,
                hideAlreadyAutomated: this._hideAlreadyAutomated,
                auditDepth: this._auditDepth,
            }));
        }
        catch {
            // Quota / private mode; non-fatal
        }
    }
    _onSearch(e) {
        this._search = e.target.value;
    }
    _onConfidence(e) {
        const value = Number(e.target.value);
        this._minConfidence = Number.isFinite(value) ? value : 0;
    }
    get _embeddedCardConfig() {
        const key = `${this._search}|${this._minConfidence}|${this._sortBy}|${this._groupBy}|` +
            `${this._filterDomains.join(",")}|${this._filterAreas.join(",")}|` +
            `${this._filterDeviceClasses.join(",")}|${this._filterDetectors.join(",")}|` +
            `${this._filterFloors.join(",")}|${this._filterIntegrations.join(",")}|` +
            `${this._filterLabels.join(",")}|` +
            `${this._hideAlreadyAutomated ? "1" : "0"}|` +
            `${this._auditDepth}`;
        if (this._cachedCardConfigKey !== key) {
            this._cachedCardConfigKey = key;
            this._cachedCardConfig = {
                type: "custom:ha-insights-card",
                title: this._search ? `Insights matching "${this._search}"` : "All insights",
                // Cap at 200 rows even on the panel. With 1000+ insights the
                // browser locks up rendering all of them; if a user really has
                // 1000+ they should use search/filter to narrow first. The card
                // shows a "showing N of M" hint when the list is truncated.
                max_rows: 200,
                min_confidence: this._minConfidence,
                search: this._search,
                sort_by: this._sortBy,
                group_by: this._groupBy,
                domain_filter: this._filterDomains,
                area_filter: this._filterAreas,
                device_class_filter: this._filterDeviceClasses,
                detector_filter: this._filterDetectors,
                floor_filter: this._filterFloors,
                integration_filter: this._filterIntegrations,
                label_filter: this._filterLabels,
                hide_already_automated: this._hideAlreadyAutomated,
                audit_depth: this._auditDepth,
            };
        }
        return this._cachedCardConfig;
    }
    async _runAuditRollup() {
        if (!this.hass || this._rollupBusy)
            return;
        this._rollupBusy = true;
        this._rollupLoopAborted = false;
        this._rollupLoopStartTs = Date.now();
        try {
            // v1.2 loop-mode: single click chains batches until all
            // entities are caught up OR a 5-minute ceiling. Each batch
            // is bounded by the backend's 120s budget + single-flight
            // lock, so we're not bypassing safety — just removing the
            // "click 12 times" UX cliff. User can stop via the Stop
            // button which sets _rollupLoopAborted.
            this.hass.connection
                .sendMessagePromise({
                type: "call_service",
                domain: "ha_insights",
                service: "run_audit_rollup",
                service_data: {},
            })
                .catch((err) => {
                this._showToast(`Rollup failed to start: ${err.message ?? String(err)}`);
            });
            // Kick the poll right away so the bar shows before the first
            // 2-second interval fires.
            await this._pollRollupProgress();
            this._startRollupPoll();
        }
        finally {
            // _rollupBusy stays sticky until the polled `running` flag
            // turns false in _pollRollupProgress.
        }
    }
    /** Hard ceiling on the auto-chain so a runaway backend can't
     *  loop forever. 5 minutes covers ≥ 1000 entities at typical
     *  rates while bounding worst-case user wait. */
    static { this._ROLLUP_LOOP_CEILING_MS = 5 * 60 * 1000; }
    _stopRollupLoop() {
        this._rollupLoopAborted = true;
    }
    _startRollupPoll() {
        if (this._rollupPollTimer !== null)
            return;
        this._rollupPollTimer = window.setInterval(() => void this._pollRollupProgress(), 2000);
    }
    _stopRollupPoll() {
        if (this._rollupPollTimer !== null) {
            window.clearInterval(this._rollupPollTimer);
            this._rollupPollTimer = null;
        }
    }
    async _pollRollupProgress() {
        if (!this.hass)
            return;
        try {
            const snap = (await this.hass.connection.sendMessagePromise({
                type: "home_insights/rollup_progress",
            }));
            this._rollupProgress = snap;
            if (!snap.running) {
                this._rollupBusy = false;
                this._stopRollupPoll();
                if (snap.last_summary && snap.finished_ts) {
                    const s = snap.last_summary;
                    const processed = s.entities_processed ?? 0;
                    const remaining = s.next_due_count ?? 0;
                    const timedOut = (s.timed_out_entities ?? []).length;
                    const elapsedMs = Date.now() - this._rollupLoopStartTs;
                    const underCeiling = elapsedMs < HaInsightsPanel._ROLLUP_LOOP_CEILING_MS;
                    // Loop-mode: if there's still work AND user hasn't
                    // stopped AND we're under the 5-min ceiling, chain
                    // another batch. Otherwise emit the final toast.
                    const shouldChain = remaining > 0 &&
                        processed > 0 && // forward progress is happening
                        !this._rollupLoopAborted &&
                        !s.skipped_inflight &&
                        underCeiling;
                    if (shouldChain) {
                        // Restart the next batch + keep polling. Brief courtesy
                        // pause lets the recorder breathe between batches.
                        window.setTimeout(() => {
                            if (!this.hass || this._rollupLoopAborted)
                                return;
                            this._rollupBusy = true;
                            this.hass.connection
                                .sendMessagePromise({
                                type: "call_service",
                                domain: "ha_insights",
                                service: "run_audit_rollup",
                                service_data: {},
                            })
                                .catch((err) => {
                                this._showToast(`Rollup chain failed: ${err.message ?? String(err)}`);
                                this._rollupBusy = false;
                            });
                            void this._pollRollupProgress();
                            this._startRollupPoll();
                        }, 1500);
                        return; // don't show terminal toast yet
                    }
                    let message;
                    if (s.skipped_inflight) {
                        message = "Rollup already running — try again in a moment";
                    }
                    else if (processed === 0 && remaining === 0 && timedOut === 0) {
                        message = "All audit rollups are already up to date ✓";
                    }
                    else if (processed === 0 && timedOut > 0) {
                        message = `No progress — ${timedOut} entities timed out, will retry`;
                    }
                    else if (remaining === 0) {
                        message = `Rollup complete: ${processed} entities caught up · all up to date ✓`;
                    }
                    else if (this._rollupLoopAborted) {
                        message = `Rollup stopped: ${remaining} entities still queued`;
                    }
                    else if (!underCeiling) {
                        message = `Rollup hit 5-min ceiling: ${remaining} entities still queued — click again to continue`;
                    }
                    else {
                        message = `Rollup batch: ${processed} advanced · ${remaining} still need work`;
                    }
                    if (s.batch_duration_sec) {
                        message += ` (${s.batch_duration_sec}s)`;
                    }
                    this._showToast(message);
                }
            }
        }
        catch (err) {
            // Endpoint not registered yet (e.g. backend not deployed) — give
            // up quietly. Without this guard the poll would spam errors
            // every 2s on older installs.
            this._stopRollupPoll();
            this._rollupBusy = false;
        }
    }
    async _fetchRecorderStatus() {
        if (!this.hass)
            return;
        try {
            this._recorderStatus = (await this.hass.connection.sendMessagePromise({
                type: "home_insights/recorder_status",
            }));
        }
        catch {
            // Endpoint may not exist on older backends — leave null.
        }
    }
    async _runBackfill() {
        if (!this.hass)
            return;
        this._backfillBusy = true;
        // Backfill triggers a re-scan internally; hide live mutations
        // until both phases complete.
        window.dispatchEvent(new CustomEvent("ha-insights-scan-start"));
        try {
            await this.hass.connection.sendMessagePromise({
                type: "call_service",
                domain: "ha_insights",
                service: "backfill",
                service_data: {},
            });
            // Poll once to get summary
            const status = (await this.hass.connection.sendMessagePromise({
                type: "home_insights/backfill_status",
            }));
            if (status.last) {
                this._showToast(`Backfilled ${status.last.events_added} events from ${status.last.entities_seen} entities (${status.last.lookback_days}d)`);
            }
            else {
                this._showToast("Backfill complete");
            }
            // Trigger a re-scan so detectors run against the new buffer contents
            await this.hass.connection.sendMessagePromise({
                type: "call_service",
                domain: "ha_insights",
                service: "scan_now",
                service_data: {},
            });
            // Force a card re-fetch so the deduped post-scan view reaches
            // the UI instead of accumulating raw subscribe-stream rows.
            window.dispatchEvent(new CustomEvent("ha-insights-refresh"));
        }
        catch (err) {
            this._showToast(`Backfill failed: ${err.message ?? String(err)}`);
        }
        finally {
            this._backfillBusy = false;
        }
    }
    async _runScanNow() {
        if (!this.hass || this._scanBusy)
            return;
        // Use the home_insights/scan_now WS endpoint instead of call_service —
        // it awaits the actual scan completion + returns a count, giving us
        // real "scan finished" feedback. call_service was returning the moment
        // the call was queued, so the user got "Scan complete" instantly while
        // the scan was still running, with no in-progress feedback.
        this._scanBusy = true;
        this._showToast("Scanning…");
        // Tell the embedded card to hide its live insight list behind a
        // "Scanning…" curtain. The subscribe stream still mutates state in
        // the background; the curtain just hides the transient un-deduped
        // view. Cleared by the matching refresh dispatch below.
        window.dispatchEvent(new CustomEvent("ha-insights-scan-start"));
        try {
            const result = await this.hass.connection.sendMessagePromise({ type: "home_insights/scan_now" });
            const noun = result.insights_emitted === 1 ? "insight" : "insights";
            const verb = result.canceled ? "canceled" : "complete";
            const parts = [
                `Scan ${verb}: ${result.insights_emitted} new ${noun} from ${result.detectors_run.length} detectors`,
            ];
            if (result.swept_stale) {
                parts.push(`${result.swept_stale} stale removed`);
            }
            if (result.suppressed_as_duplicate) {
                parts.push(`${result.suppressed_as_duplicate} dup-of-existing-automation suppressed`);
            }
            this._showToast(parts.join(" · "));
            // Tell the embedded card to re-fetch insights via ws_list. Without
            // this, the card's subscribe stream may have accumulated stale
            // pre-dedup rows from the in-progress scan; ws_list returns the
            // canonical deduped view.
            window.dispatchEvent(new CustomEvent("ha-insights-refresh"));
        }
        catch (err) {
            this._showToast(`Scan failed: ${err.message ?? String(err)}`);
        }
        finally {
            this._scanBusy = false;
        }
    }
    async _cancelScan() {
        if (!this.hass || !this._scanBusy)
            return;
        try {
            await this.hass.connection.sendMessagePromise({
                type: "home_insights/cancel_scan",
            });
            this._showToast("Stopping scan…");
        }
        catch (err) {
            this._showToast(`Cancel failed: ${err.message ?? String(err)}`);
        }
    }
    /** Force the browser to pick up a freshly-deployed panel/card bundle.
     *  Two-step: (1) ask the integration to re-register the panel with a
     *  fresh ?v= mtime/size signature so the URL changes; (2) hard-reload
     *  the window so the browser bypasses its HTTP cache + service worker.
     *  Without (1), the URL stays the same and the browser SW keeps the
     *  old bundle. Without (2), the new ?v= is queued but the current tab
     *  is still running old code. Both pieces matter. */
    async _reloadUi() {
        if (!this.hass)
            return;
        try {
            await this.hass.connection.sendMessagePromise({
                type: "call_service",
                domain: "ha_insights",
                service: "reload_ui",
                service_data: {},
            });
            this._showToast("Reloading bundle…");
            // Give the toast a tick to paint, then force a cache-bypassing
            // reload. `location.reload(true)` is deprecated; the modern path
            // is `location.reload()` after navigating to a query-busted URL.
            window.setTimeout(() => {
                const url = new URL(window.location.href);
                url.searchParams.set("_reload", String(Date.now()));
                window.location.replace(url.toString());
            }, 200);
        }
        catch (err) {
            this._showToast(`Reload failed: ${err.message ?? String(err)}`);
        }
    }
    async _purgeAllInsights() {
        if (!this.hass)
            return;
        const confirmed = window.confirm("Delete ALL stored insights from this integration?\n\n" +
            "This wipes the insights table + outbound LLM call audit log. " +
            "Applied-automation history and pseudonym map are preserved. " +
            "Useful when a noisy scan filled the panel with thousands of " +
            "spurious insights — clean slate, click Run Scan Now again.");
        if (!confirmed)
            return;
        try {
            await this.hass.connection.sendMessagePromise({
                type: "call_service",
                domain: "ha_insights",
                service: "purge_observations",
                service_data: {},
            });
            // v1.2.22: explicit "purged" event the card listens for. Sets
            // a 30s suppression window during which new "added" subscribe
            // events are ignored. Without this, the user clicks Purge and
            // immediately sees insights repopulate from the next scan_
            // interval-driven scan — which violates the "I wanted a clean
            // slate" mental model even though the data IS being correctly
            // re-detected.
            window.dispatchEvent(new CustomEvent("ha-insights-purged", {
                detail: { suppressionMs: 30_000 },
            }));
            this._showToast("Purged. New detections suppressed for 30s — click Scan now to refresh sooner.");
        }
        catch (err) {
            this._showToast(`Purge failed: ${err.message ?? String(err)}`);
        }
    }
    /** v1.10.4: fetch the redacted dev-audit bundle and open the modal.
     *
     *  The bundle (see lib/dev_audit.py SCHEMA_VERSION) captures install
     *  signature + per-detector activity + buffer signature + config
     *  fingerprint — all redacted so the user can safely paste it into a
     *  GitHub issue OR into an AI chat asking "are any detectors silent
     *  for the wrong reason?"
     *
     *  Admin-only at the WS layer; the button is only useful for users
     *  who can also access HA Developer Tools. We don't pre-gate visibility
     *  on the card side because non-admin users may legitimately want to
     *  see what's there (the bundle is redacted by design). */
    async _runDiagnostics() {
        if (!this.hass)
            return;
        this._diagnosticsBusy = true;
        try {
            const result = await this.hass.connection.sendMessagePromise({
                type: "home_insights/export_dev_audit",
            });
            this._diagnosticsJson = JSON.stringify(result, null, 2);
        }
        catch (err) {
            this._showToast(`Diagnostics failed: ${err.message ?? String(err)}`);
        }
        finally {
            this._diagnosticsBusy = false;
        }
    }
    /** Copy the loaded diagnostics JSON to the user's clipboard. Uses the
     *  modern Clipboard API; falls back gracefully when not available
     *  (e.g. running in an insecure context). */
    async _copyDiagnostics() {
        if (!this._diagnosticsJson)
            return;
        try {
            await navigator.clipboard.writeText(this._diagnosticsJson);
            this._showToast("Diagnostics copied to clipboard. Paste into a GitHub issue or your AI chat.");
        }
        catch (err) {
            this._showToast(`Clipboard copy failed: ${err.message ?? String(err)}`);
        }
    }
    _closeDiagnostics() {
        this._diagnosticsJson = null;
    }
    // ===== v1.10.8 — Find My HA Device =====
    /** Open the Find Device modal. Resets selection + counter so each
     *  session starts clean. */
    _openFindDevice() {
        this._findDeviceOpen = true;
        this._findDeviceSearch = "";
        this._findDeviceSelected = new Set();
        this._findDeviceCount = 0;
        this._findDeviceErrors = {};
    }
    /** Close the modal and clear the recurring identify timer +
     *  any active watch-mode subscriptions. */
    _closeFindDevice() {
        if (this._findDeviceTimer != null) {
            clearInterval(this._findDeviceTimer);
            this._findDeviceTimer = null;
        }
        // Tear down every active state_changed subscription. Each unsub
        // is wrapped so we don't need to await Promises here.
        for (const unsub of this._findDeviceWatchUnsubs.values()) {
            try {
                unsub();
            }
            catch {
                // best-effort cleanup
            }
        }
        this._findDeviceWatchUnsubs.clear();
        const stoppedWithSelection = this._findDeviceSelected.size > 0;
        this._findDeviceOpen = false;
        this._findDeviceSelected = new Set();
        this._findDeviceErrors = {};
        this._findDeviceCount = 0;
        this._findDeviceFireCounts = {};
        this._findDeviceSessionStartedAt = 0;
        this._findDeviceSessionElapsedMs = 0;
        this._findDevicePowerCycleConfirmed = new Set();
        this._findDeviceWatchBaselines = {};
        this._findDeviceWatchCurrent = {};
        this._findDeviceWatchDetected = new Set();
        if (stoppedWithSelection) {
            this._showToast("🔍 Identification stopped.");
        }
    }
    _toggleFindDeviceEntity(entityId) {
        const next = new Set(this._findDeviceSelected);
        const state = this.hass?.states?.[entityId];
        const mode = state
            ? this._findDeviceMode(entityId, state)
            : null;
        if (next.has(entityId)) {
            next.delete(entityId);
            const errs = { ...this._findDeviceErrors };
            delete errs[entityId];
            this._findDeviceErrors = errs;
            const counts = { ...this._findDeviceFireCounts };
            delete counts[entityId];
            this._findDeviceFireCounts = counts;
            // Tear down watch-mode subscription if present.
            const unsub = this._findDeviceWatchUnsubs.get(entityId);
            if (unsub) {
                unsub();
                this._findDeviceWatchUnsubs.delete(entityId);
            }
            const baselines = { ...this._findDeviceWatchBaselines };
            delete baselines[entityId];
            this._findDeviceWatchBaselines = baselines;
            const cur = { ...this._findDeviceWatchCurrent };
            delete cur[entityId];
            this._findDeviceWatchCurrent = cur;
            const det = new Set(this._findDeviceWatchDetected);
            det.delete(entityId);
            this._findDeviceWatchDetected = det;
        }
        else {
            next.add(entityId);
            if (mode === "perturb" || mode === "watch") {
                this._startEntityWatch(entityId, mode);
            }
        }
        this._findDeviceSelected = next;
        // Fire-loop timer only matters when at least one fire-mode entity
        // is selected. Watch-mode entities use HA state subscriptions
        // independently, so an all-watch selection should NOT spin the
        // identify loop unnecessarily.
        const hasFireEntities = Array.from(next).some((eid) => {
            const st = this.hass?.states?.[eid];
            return st && this._findDeviceMode(eid, st) === "fire";
        });
        if (hasFireEntities && this._findDeviceTimer == null) {
            this._findDeviceSessionStartedAt = Date.now();
            this._findDeviceSessionElapsedMs = 0;
            void this._fireFindDeviceOnce();
            this._findDeviceTimer = setInterval(() => void this._fireFindDeviceOnce(), 1000);
        }
        else if (!hasFireEntities && this._findDeviceTimer != null) {
            clearInterval(this._findDeviceTimer);
            this._findDeviceTimer = null;
            this._findDeviceSessionStartedAt = 0;
            this._findDeviceSessionElapsedMs = 0;
        }
    }
    /** Subscribe to state changes on an entity and watch for a touch
     *  (sensor) or trigger (binary_sensor). Captures a baseline value
     *  on first subscription and stamps `_findDeviceWatchDetected`
     *  once the delta exceeds the per-device_class threshold.
     *
     *  Uses HA's standard `state_changed` event subscription, filtered
     *  client-side by entity_id. No backend endpoint needed — the
     *  card watches the regular state stream the user can already
     *  see in Developer Tools. */
    _startEntityWatch(entityId, mode) {
        if (!this.hass || this._findDeviceWatchUnsubs.has(entityId))
            return;
        const initial = this.hass.states?.[entityId];
        if (mode === "perturb") {
            const baseline = parseFloat(initial?.state ?? "");
            if (Number.isFinite(baseline)) {
                this._findDeviceWatchBaselines = {
                    ...this._findDeviceWatchBaselines,
                    [entityId]: baseline,
                };
            }
        }
        if (initial) {
            this._findDeviceWatchCurrent = {
                ...this._findDeviceWatchCurrent,
                [entityId]: initial.state,
            };
        }
        const handle = (evt) => {
            if (evt.data?.entity_id !== entityId)
                return;
            const newState = evt.data.new_state?.state;
            if (newState === undefined)
                return;
            this._findDeviceWatchCurrent = {
                ...this._findDeviceWatchCurrent,
                [entityId]: newState,
            };
            if (mode === "perturb") {
                const baseline = this._findDeviceWatchBaselines[entityId];
                const v = parseFloat(newState);
                if (!Number.isFinite(v) || !Number.isFinite(baseline))
                    return;
                const deviceClass = initial?.attributes?.device_class;
                if (typeof deviceClass !== "string")
                    return;
                const threshold = PERTURBATION_DETECTION_THRESHOLDS[deviceClass] ?? 1.0;
                if (Math.abs(v - baseline) >= threshold) {
                    const det = new Set(this._findDeviceWatchDetected);
                    det.add(entityId);
                    this._findDeviceWatchDetected = det;
                }
            }
            else if (mode === "watch") {
                if (newState === "on") {
                    const det = new Set(this._findDeviceWatchDetected);
                    det.add(entityId);
                    this._findDeviceWatchDetected = det;
                }
            }
        };
        // HassLite types subscribeMessage but not subscribeEvents — the
        // underlying ha-websocket-js connection exposes both. Cast to
        // access subscribeEvents since it's the simpler primitive (just
        // an event type string, vs. a full WS command). Runtime-safe;
        // HA has shipped subscribeEvents since 2020.
        const conn = this.hass.connection;
        void conn.subscribeEvents(handle, "state_changed").then((unsub) => {
            // If the user already unchecked while we were waiting for
            // the subscription to be ready, tear it down immediately.
            if (!this._findDeviceSelected.has(entityId)) {
                void unsub();
                return;
            }
            this._findDeviceWatchUnsubs.set(entityId, () => void unsub());
        });
    }
    /** Format remaining session time as `m:ss`. Hits 0:00 right before
     *  the auto-stop fires, so the toast is the visual confirmation. */
    _formatFindDeviceRemaining() {
        const elapsed = this._findDeviceSessionElapsedMs;
        const remaining = Math.max(0, FIND_DEVICE_MAX_SESSION_MS - elapsed);
        const totalSec = Math.ceil(remaining / 1000);
        const m = Math.floor(totalSec / 60);
        const s = totalSec % 60;
        return `${m}:${s.toString().padStart(2, "0")}`;
    }
    async _fireFindDeviceOnce() {
        if (!this.hass || this._findDeviceSelected.size === 0)
            return;
        const now = Date.now();
        // Session-level safety ceiling. Auto-stop everything after the
        // hard maximum. Toast tells the user why and how to resume.
        if (this._findDeviceSessionStartedAt > 0) {
            this._findDeviceSessionElapsedMs = now - this._findDeviceSessionStartedAt;
            if (this._findDeviceSessionElapsedMs >= FIND_DEVICE_MAX_SESSION_MS) {
                if (this._findDeviceTimer != null) {
                    clearInterval(this._findDeviceTimer);
                    this._findDeviceTimer = null;
                }
                this._findDeviceSelected = new Set();
                this._findDeviceSessionStartedAt = 0;
                this._showToast("🔍 Auto-stopped after 5 min. Re-check entities to keep looking.");
                return;
            }
        }
        // Pick entities that are DUE to fire this tick based on their
        // per-domain cadence + last-fired timestamp. Also enforces the
        // per-entity fire-count ceiling.
        const due = [];
        const nextSelected = new Set(this._findDeviceSelected);
        const nextCounts = { ...this._findDeviceFireCounts };
        for (const entityId of this._findDeviceSelected) {
            const fires = nextCounts[entityId] ?? 0;
            if (fires >= FIND_DEVICE_MAX_FIRES_PER_ENTITY) {
                // This entity hit its individual ceiling. Quietly remove
                // it from the active loop — the user still sees the row,
                // can re-check to resume, but the loop stops accumulating
                // toggles on a possibly-abandoned entity.
                nextSelected.delete(entityId);
                continue;
            }
            const domain = entityId.split(".", 1)[0];
            const cadence = FIND_DEVICE_CADENCE_MS[domain] ?? FIND_DEVICE_DEFAULT_CADENCE_MS;
            const last = this._findDeviceLastFiredAt[entityId] ?? 0;
            if (last === 0 || now - last >= cadence) {
                due.push(entityId);
            }
        }
        if (nextSelected.size !== this._findDeviceSelected.size) {
            this._findDeviceSelected = nextSelected;
        }
        if (due.length === 0) {
            this._findDeviceFireCounts = nextCounts;
            return;
        }
        const results = await Promise.allSettled(due.map((entityId) => this.hass.connection.sendMessagePromise({
            type: "home_insights/identify_entity",
            entity_id: entityId,
            confirm_power_cycle: this._findDevicePowerCycleConfirmed.has(entityId),
        })));
        const nextErrors = { ...this._findDeviceErrors };
        for (let i = 0; i < results.length; i++) {
            const r = results[i];
            const entityId = due[i];
            this._findDeviceLastFiredAt[entityId] = now;
            if (r.status === "rejected") {
                const err = r.reason;
                nextErrors[entityId] = err.message ?? String(err);
                // Don't count failed fires against the cap — keyword refusals
                // would otherwise hit 30 instantly and the row would auto-drop
                // before the user noticed the error.
            }
            else if (r.value.requires_confirmation) {
                // Backend asked for explicit power-cycle confirmation.
                // Synchronous browser confirm() is OK here — modal is already
                // blocking the page, this just adds another layer.
                const warning = r.value.warning ??
                    `Power-cycle ${entityId}? This will turn it on/off.`;
                const ok = window.confirm(`⚠️ Confirm power-cycle\n\n${warning}\n\n` +
                    "Click OK to allow. Click Cancel to skip this entity " +
                    "(stays in selection but won't fire).");
                if (ok) {
                    this._findDevicePowerCycleConfirmed.add(entityId);
                    // Don't count this tick; next tick will retry with the
                    // confirmation flag set and actually fire.
                }
                else {
                    nextErrors[entityId] = "User declined power-cycle confirmation.";
                    // Remove from active loop — keep checkbox visible but
                    // don't keep prompting.
                    const drop = new Set(this._findDeviceSelected);
                    drop.delete(entityId);
                    this._findDeviceSelected = drop;
                }
            }
            else {
                nextCounts[entityId] = (nextCounts[entityId] ?? 0) + 1;
                delete nextErrors[entityId];
            }
        }
        this._findDeviceErrors = nextErrors;
        this._findDeviceFireCounts = nextCounts;
        this._findDeviceCount = this._findDeviceCount + 1;
    }
    /** Decide if an entity is findable via Find Device. Three modes:
     *
     *  - "fire": light / switch / media_player / siren — runs the
     *    backend identify loop (light flash, switch toggle, chime).
     *  - "perturb": sensor with a perturbable device_class — user
     *    touches the sensor, we watch for a state delta.
     *  - "watch": motion / occupancy / contact / vibration binary
     *    sensor — user walks through / opens, we watch for off→on. */
    _findDeviceMode(entity_id, state) {
        const domain = entity_id.split(".", 1)[0];
        if (FINDABLE_DOMAINS.has(domain))
            return "fire";
        const deviceClass = state.attributes?.device_class;
        if (typeof deviceClass !== "string")
            return null;
        if (domain === "sensor" && PERTURBABLE_DEVICE_CLASSES.has(deviceClass)) {
            return "perturb";
        }
        if (domain === "binary_sensor" &&
            WATCHABLE_BINARY_DEVICE_CLASSES.has(deviceClass)) {
            return "watch";
        }
        return null;
    }
    /** Filter the entity list to entries matching the user's search
     *  string. Case-insensitive substring match on entity_id +
     *  friendly_name. Capped at 100 results so the DOM stays
     *  responsive on installs with thousands of entities.
     *
     *  Three buckets: physically-firable (light/switch/media/siren),
     *  perturbable sensors (temp/humidity/CO₂/etc.), and watchable
     *  binary sensors (motion/occupancy/contact). Software-only
     *  domains (automation/scene/script/calendar) are dropped because
     *  they have no physical presence to locate. */
    _findDeviceMatches() {
        if (!this.hass?.states)
            return [];
        const needle = this._findDeviceSearch.trim().toLowerCase();
        const out = [];
        for (const [entity_id, state] of Object.entries(this.hass.states)) {
            const mode = this._findDeviceMode(entity_id, state);
            if (mode === null)
                continue;
            const friendly = state.attributes?.friendly_name ?? entity_id;
            if (!needle) {
                out.push({ entity_id, friendly_name: friendly, mode });
            }
            else {
                const hay = `${entity_id} ${friendly}`.toLowerCase();
                if (hay.includes(needle)) {
                    out.push({ entity_id, friendly_name: friendly, mode });
                }
            }
            if (out.length >= 100)
                break;
        }
        return out.sort((a, b) => {
            // Group by mode (fire first), then alphabetical inside group —
            // helps users find the right entity when many domains match.
            const modeOrder = { fire: 0, perturb: 1, watch: 2 };
            if (a.mode !== b.mode)
                return modeOrder[a.mode] - modeOrder[b.mode];
            return a.entity_id.localeCompare(b.entity_id);
        });
    }
    /** Bulk-apply all currently-visible insights (after the panel's filters
     *  have been applied). Confirms first because each apply writes a real
     *  automation. Best for power users triaging a backlog after a long
     *  detection run; not exposed on the dashboard card. */
    async _runBulkApply() {
        if (!this.hass)
            return;
        // Pull the same filtered list the embedded card is rendering. We query
        // the WS API directly so the panel doesn't have to peek into the
        // card's internals.
        let visible = [];
        try {
            const result = await this.hass.connection.sendMessagePromise({ type: "home_insights/list" });
            const search = this._search.trim().toLowerCase();
            visible = result.insights
                .filter((i) => i.confidence >= this._minConfidence)
                .filter((i) => !search || i.title.toLowerCase().includes(search))
                .filter((i) => i.payload_format === "automation");
        }
        catch (err) {
            this._showToast(`Could not list: ${err.message ?? String(err)}`);
            return;
        }
        if (visible.length === 0) {
            this._showToast("Nothing to apply (no automation insights match)");
            return;
        }
        const proceed = window.confirm(`Apply ${visible.length} insight${visible.length === 1 ? "" : "s"}? `
            + "Each will write a real Home Assistant automation. "
            + "Refined / renamed / edited drafts on individual insights are NOT used "
            + "by bulk apply — only the original detected payload.");
        if (!proceed)
            return;
        this._bulkBusy = true;
        let succeeded = 0;
        const errors = [];
        try {
            for (const insight of visible) {
                try {
                    await this.hass.connection.sendMessagePromise({
                        type: "home_insights/apply",
                        insight_id: insight.id,
                    });
                    succeeded += 1;
                }
                catch (err) {
                    const message = err.message ?? String(err);
                    errors.push(`${insight.title}: ${message}`);
                }
            }
        }
        finally {
            this._bulkBusy = false;
        }
        if (errors.length === 0) {
            this._showToast(`Applied all ${succeeded}`);
        }
        else {
            this._showToast(`Applied ${succeeded} / ${visible.length}; ${errors.length} error(s) — first: ${errors[0]}`);
        }
    }
    _showToast(message) {
        this._toast = message;
        window.clearTimeout(this._toastTimer);
        this._toastTimer = window.setTimeout(() => {
            this._toast = "";
        }, 3500);
    }
    async _toggleAudit() {
        if (this._auditOpen) {
            this._auditOpen = false;
            return;
        }
        this._auditOpen = true;
        if (this._auditLog.length === 0) {
            await this._loadAuditLog();
        }
    }
    async _loadAuditLog() {
        if (!this.hass)
            return;
        this._auditBusy = true;
        try {
            const result = await this.hass.connection.sendMessagePromise({ type: "home_insights/audit_log", limit: 25 });
            this._auditLog = result.calls;
        }
        catch (err) {
            this._showToast(`Audit log failed: ${err.message ?? String(err)}`);
        }
        finally {
            this._auditBusy = false;
        }
    }
    _renderAuditLog() {
        return b `
      <div class="audit">
        <div
          class="audit-toggle ${this._auditOpen ? "open" : ""}"
          @click=${this._toggleAudit}
        >
          <h3>🛡️ LLM activity (${this._auditLog.length || "—"})</h3>
          <span class="arrow">▶</span>
        </div>
        ${this._auditOpen
            ? this._auditBusy
                ? b `<div class="audit-empty">Loading…</div>`
                : this._auditLog.length === 0
                    ? b `<div class="audit-empty">
                  No LLM calls recorded yet. When you click Explain or
                  Refine on an insight, each call lands here.
                </div>`
                    : b `
                  <ul class="audit-list">
                    ${this._auditLog.map((c) => this._renderAuditRow(c))}
                  </ul>
                `
            : ""}
      </div>
    `;
    }
    _renderAuditRow(c) {
        const when = new Date(c.timestamp);
        const local = when.toLocaleString();
        const success = c.success === true;
        const fail = c.success === false;
        const icon = success ? "✓" : fail ? "✗" : "·";
        const iconCls = success
            ? "audit-icon-ok"
            : fail
                ? "audit-icon-fail"
                : "";
        const title = c.insight_title ?? (c.insight_id ? `[deleted ${c.insight_id.slice(0, 8)}]` : "(unknown insight)");
        return b `
      <li>
        <span class="audit-icon ${iconCls}">${icon}</span>
        <div>
          <div>${title}</div>
          <div class="audit-meta">
            ${local} · ${c.agent} · ${c.redaction_mode}
          </div>
        </div>
        <div class="audit-bytes">
          ↑${c.bytes_sent}b / ↓${c.bytes_received}b
        </div>
      </li>
    `;
    }
    render() {
        return b `
      <div class="header">
        <div class="titles">
          <h1>HA Insights</h1>
          <div class="sub">
            Patterns the integration noticed in your home — apply, refine, test, or dismiss each.
          </div>
          ${this._renderDetectorCounts()}
        </div>
        <div class="actions">
          <button
            class="action"
            ?disabled=${this._backfillBusy}
            aria-label="Backfill state-event buffer from recorder"
            title="Re-populate the buffer from HA's recorder"
            @click=${this._runBackfill}
          >
            ${this._backfillBusy
            ? "Backfilling…"
            : b `<ha-icon icon="mdi:database-refresh"></ha-icon> Backfill`}
          </button>
          <button
            class="action"
            ?disabled=${this._rollupBusy}
            aria-label="Run audit rollup against recorder history"
            title="Recompute long-term audit rollups (day-of-week / month-of-year buckets) from HA's recorder. Single click chains batches until everything is caught up OR 5-minute ceiling — Stop button interrupts."
            @click=${this._runAuditRollup}
          >
            ${this._rollupBusy
            ? "Rolling up…"
            : b `<ha-icon icon="mdi:calendar-clock"></ha-icon> Run audit rollup`}
          </button>
          ${this._rollupBusy
            ? b `<button
                class="action"
                aria-label="Stop audit rollup loop"
                title="Stop chaining batches. The current batch finishes; no new batch is started."
                @click=${this._stopRollupLoop}
              >
                <ha-icon icon="mdi:stop"></ha-icon> Stop rollup
              </button>`
            : ""}
          <button
            class="action primary"
            ?disabled=${this._scanBusy}
            aria-label="Run all detectors now"
            title="Run all detectors against the current buffer"
            @click=${this._runScanNow}
          >
            ${this._scanBusy
            ? "Scanning…"
            : b `<ha-icon icon="mdi:magnify-scan"></ha-icon> Scan now`}
          </button>
          ${this._scanBusy
            ? b `<button
                class="action"
                aria-label="Stop the in-flight scan"
                title="Stop the in-flight scan after the current detector"
                @click=${this._cancelScan}
              >
                <ha-icon icon="mdi:stop"></ha-icon> Stop
              </button>`
            : ""}
          <button
            class="action"
            aria-label="Reload HA Insights UI"
            title="Re-register the panel with a fresh cache-bust + force browser reload — use after deploying a new ha-insights-card.js / panel.js"
            @click=${this._reloadUi}
          >
            <ha-icon icon="mdi:refresh"></ha-icon> Reload UI
          </button>
          <button
            class="action"
            aria-label="Purge all stored insights"
            title="Delete every stored insight (useful when a noisy scan filled the list)"
            @click=${this._purgeAllInsights}
          >
            <ha-icon icon="mdi:delete-sweep-outline"></ha-icon> Purge all
          </button>
          <button
            class="action"
            ?disabled=${this._diagnosticsBusy}
            aria-label="Export redacted diagnostics bundle"
            title="Capture a redacted snapshot of the install (per-detector activity counts, install signature, config fingerprint). Safe to paste into a GitHub issue or an AI chat to ask 'are any of my detectors silent for the wrong reason?'"
            @click=${this._runDiagnostics}
          >
            ${this._diagnosticsBusy
            ? "Collecting…"
            : b `<ha-icon icon="mdi:magnify-expand"></ha-icon> 🔬 Diagnostics`}
          </button>
          <button
            class="action"
            aria-label="Find a device in your home"
            title="Pick any entity in your install and the integration fires its native identifier (light flash, speaker chime, fan flicker, etc.) every 5 seconds until you click 'Found it!'. Useful for locating an unfamiliar entity like 'light.0x0015...' or 'switch.unnamed_3'."
            @click=${this._openFindDevice}
          >
            <ha-icon icon="mdi:map-search"></ha-icon> 🔍 Find device
          </button>
          <button
            class="action"
            ?disabled=${this._bulkBusy}
            aria-label="Apply every visible automation insight"
            title="Apply every visible automation insight (respects search + confidence filters)"
            @click=${this._runBulkApply}
          >
            ${this._bulkBusy
            ? "Applying…"
            : b `<ha-icon icon="mdi:check-all"></ha-icon> Apply all visible`}
          </button>
        </div>
      </div>
      ${this._renderRollupProgress()}
      <div class="filters">
        <input
          type="search"
          placeholder="Search insights (title)…"
          .value=${this._search}
          @input=${this._onSearch}
        />
        <label class="conf">
          Min confidence: ${Math.round(this._minConfidence * 100)}%
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            .value=${String(this._minConfidence)}
            @input=${this._onConfidence}
          />
        </label>
        <select
          aria-label="Sort by"
          .value=${this._sortBy}
          @change=${(e) => (this._sortBy = e.target
            .value)}
        >
          <option value="confidence">Sort: Confidence</option>
          <option value="age">Sort: Newest</option>
          <option value="detector">Sort: Detector</option>
        </select>
        <select
          aria-label="Group by"
          .value=${this._groupBy}
          @change=${(e) => (this._groupBy = e.target
            .value)}
        >
          <option value="none">Group: None</option>
          <option value="detector">Group: Detector</option>
          <option value="area">Group: Area</option>
          <option value="floor">Group: Floor</option>
          <option value="integration">Group: Integration</option>
          <option value="label">Group: Label</option>
        </select>
        <select
          aria-label="Audit suggest analysis depth"
          title="Controls how much reasoning the LLM does on 🤖 Suggest. Concise = ~150 token rules (cheap). In-depth = ~600 token rules with examples (better answers, ~4× input tokens)."
          .value=${this._auditDepth}
          @change=${(e) => (this._auditDepth = e.target
            .value)}
        >
          <option value="concise">🤖 Concise (cheap)</option>
          <option value="indepth">🤖 In-depth (4× tokens)</option>
        </select>
        <label
          style="display:inline-flex; align-items:center; gap:6px; font-size:0.9em; cursor:pointer;"
          title="Hide insights that the conflict scanner already marked as covered by an existing automation (🔁 already automated)."
        >
          <input
            type="checkbox"
            .checked=${this._hideAlreadyAutomated}
            @change=${(e) => (this._hideAlreadyAutomated = e.target.checked)}
          />
          Hide 🔁 already automated
        </label>
      </div>
      ${this._renderChipFilters()}
      <div class="filters" style="padding-top:0; padding-bottom:8px;">
        <span style="font-size:0.85em; color: var(--secondary-text-color);">
          Showing ${this._visibleInsightCount} of ${this._totalInsightCount}
          insight${this._totalInsightCount === 1 ? "" : "s"}
          ${this._anyChipActive()
            ? b `<a
                href="#"
                style="margin-left:8px;"
                @click=${(e) => {
                e.preventDefault();
                this._clearChipFilters();
            }}
                >clear filters</a
              >`
            : ""}
        </span>
      </div>
      <div class="body">
        ${this._renderCard()}
      </div>
      ${this._renderAuditLog()}
      ${this._renderDiagnosticsModal()}
      ${this._renderFindDeviceModal()}
      ${this._toast ? b `<div class="toast">${this._toast}</div>` : ""}
    `;
    }
    /** v1.10.8: Find My HA Device modal. Top-level entity picker that
     *  lets users locate ANY entity, not just ones surfaced in insights.
     *
     *  UI:
     *   - Search input (live-filters entities by entity_id / friendly_name)
     *   - Scrollable list capped at 100 results (DOM perf on big installs)
     *   - Each row: checkbox + entity_id (mono) + friendly_name
     *   - Footer: "{N} selected, fired {C} times" + Found / Stop buttons
     *   - Per-entity error pills surface alongside the checkbox row when
     *     a fire fails (entity doesn't support identify, etc.)
     *
     *  Behaviour: checking an entity adds it to the looping fire set;
     *  unchecking removes it. Loop is started/stopped automatically by
     *  _toggleFindDeviceEntity based on set size. No per-entity action
     *  needed — just check, listen, uncheck when found. */
    _renderFindDeviceModal() {
        if (!this._findDeviceOpen)
            return "";
        const matches = this._findDeviceMatches();
        const selectedCount = this._findDeviceSelected.size;
        return b `
      <div class="diagnostics-backdrop" @click=${this._closeFindDevice}>
        <div
          class="diagnostics-dialog find-device-dialog"
          @click=${(e) => e.stopPropagation()}
        >
          <div class="diagnostics-header">
            <strong>🔍 Find a device</strong>
            <button
              class="diagnostics-close"
              aria-label="Close"
              @click=${this._closeFindDevice}
            >×</button>
          </div>
          <div class="diagnostics-body">
            <p class="diagnostics-hint">
              Only entities with a built-in identifier are listed:
              lights (flash / strobe), switches (toggle click), media
              players (chime), sirens (chirp). Automations, scenes,
              and scripts are software constructs — they have no
              physical body to find. Pick any entity below and the
              integration fires its native identifier every 5 seconds
              until you uncheck it.
            </p>
            <p class="diagnostics-hint" style="color: var(--secondary-text-color); font-size: 0.85em;">
              💡 <strong>Passive sensors</strong> (👆 temperature / humidity /
              CO₂ / illuminance / sound / moisture) and <strong>binary
              sensors</strong> (👀 motion / occupancy / contact / vibration)
              are listed here too. Tick one and the row will show its
              live state — touch / wave at / open the device and the
              row turns green when the spike is detected. No services
              fired; just a state-stream watch.
            </p>
            <p class="diagnostics-hint" style="color: var(--secondary-text-color); font-size: 0.85em;">
              ⚠️ <strong>Safety:</strong> sessions auto-stop after 5
              minutes; each entity tops out at 30 fires. Lights pulse
              brightness without power-cycling (safe for Tuya / Aqara /
              Hue, which interpret rapid on/off as pairing-mode
              triggers); switches click twice every 12 s so the
              aggregate looks like a human searching. If a switch is
              hard-wired to a smart bulb, the bulb will flicker too —
              that's how the wiring is, not a bug.
            </p>
            <input
              type="search"
              class="find-device-search"
              placeholder="Search entity_id or friendly_name…"
              .value=${this._findDeviceSearch}
              @input=${(e) => (this._findDeviceSearch = e.target.value)}
            />
            <div class="find-device-status">
              ${selectedCount} selected · fired ${this._findDeviceCount}
              ${this._findDeviceCount === 1 ? "time" : "times"}
              ${this._findDeviceTimer != null
            ? b ` · auto-stop in
                    ${this._formatFindDeviceRemaining()}`
            : ""}
            </div>
            <div class="find-device-list">
              ${matches.length === 0
            ? b `<div class="find-device-empty">No matching entities.</div>`
            : matches.map((m) => {
                const err = this._findDeviceErrors[m.entity_id];
                const checked = this._findDeviceSelected.has(m.entity_id);
                const detected = this._findDeviceWatchDetected.has(m.entity_id);
                const baseline = this._findDeviceWatchBaselines[m.entity_id];
                const current = this._findDeviceWatchCurrent[m.entity_id];
                const fires = this._findDeviceFireCounts[m.entity_id] ?? 0;
                const st = this.hass?.states?.[m.entity_id];
                const deviceClass = st?.attributes?.device_class;
                const unit = st?.attributes?.unit_of_measurement;
                return b `
                      <label
                        class="find-device-row find-device-row--${m.mode} ${detected
                    ? "find-device-row--detected"
                    : ""}"
                      >
                        <input
                          type="checkbox"
                          ?checked=${checked}
                          @change=${() => this._toggleFindDeviceEntity(m.entity_id)}
                        />
                        <div class="find-device-row-text">
                          <span class="find-device-eid">
                            ${m.mode === "perturb"
                    ? "👆 "
                    : m.mode === "watch"
                        ? "👀 "
                        : ""}${m.entity_id}
                          </span>
                          <span class="find-device-name">${m.friendly_name}</span>
                          ${m.mode === "fire" && checked && fires > 0
                    ? b `<span class="find-device-fires"
                                >fired ${fires}/${FIND_DEVICE_MAX_FIRES_PER_ENTITY}</span
                              >`
                    : ""}
                          ${m.mode === "perturb" && checked
                    ? b `<span class="find-device-watch-hint">
                                ${detected
                        ? b `<strong style="color: var(--success-color, #4caf50);">
                                      ✅ Spike detected — this is your sensor!
                                    </strong>`
                        : b `Touch / breathe on / cover this sensor.
                                      Baseline ${baseline?.toFixed(1) ?? "—"}${unit ?? ""},
                                      now <strong>${current ?? "—"}${unit ?? ""}</strong>`}
                              </span>`
                    : ""}
                          ${m.mode === "watch" && checked
                    ? b `<span class="find-device-watch-hint">
                                ${detected
                        ? b `<strong style="color: var(--success-color, #4caf50);">
                                      ✅ Triggered — this is the ${deviceClass ?? "sensor"}!
                                    </strong>`
                        : b `Walk past / open / wave. Current state:
                                      <strong>${current ?? "—"}</strong>`}
                              </span>`
                    : ""}
                          ${err
                    ? b `<span class="find-device-err">${err}</span>`
                    : ""}
                        </div>
                      </label>
                    `;
            })}
            </div>
            ${matches.length >= 100
            ? b `<div class="find-device-truncated">
                  Showing first 100 — refine your search to narrow.
                </div>`
            : ""}
          </div>
          <div class="diagnostics-actions">
            <button class="action primary" @click=${this._closeFindDevice}>
              ✅ Found them all — close
            </button>
          </div>
        </div>
      </div>
    `;
    }
    /** v1.10.4: diagnostics modal — shows the redacted dev-audit JSON
     *  with copy-to-clipboard for AI chat / bug reports. Only rendered
     *  when _diagnosticsJson is non-null. */
    _renderDiagnosticsModal() {
        if (this._diagnosticsJson === null)
            return "";
        return b `
      <div class="diagnostics-backdrop" @click=${this._closeDiagnostics}>
        <div
          class="diagnostics-dialog"
          @click=${(e) => e.stopPropagation()}
        >
          <div class="diagnostics-header">
            <strong>🔬 Redacted diagnostics</strong>
            <button
              class="diagnostics-close"
              aria-label="Close"
              @click=${this._closeDiagnostics}
            >×</button>
          </div>
          <div class="diagnostics-body">
            <p class="diagnostics-hint">
              Snapshot of your install — entity counts by domain,
              per-detector activity, config fingerprint. Entity friendly
              names, automation aliases, IPs and lat/long are NOT
              included. Safe to paste into a GitHub issue or an AI chat
              ("are any of my detectors silent for the wrong reason?").
            </p>
            <pre class="diagnostics-json">${this._diagnosticsJson}</pre>
          </div>
          <div class="diagnostics-actions">
            <button
              class="action primary"
              @click=${this._copyDiagnostics}
            >
              <ha-icon icon="mdi:content-copy"></ha-icon>
              Copy to clipboard
            </button>
            <button class="action" @click=${this._closeDiagnostics}>
              Close
            </button>
          </div>
        </div>
      </div>
    `;
    }
    _anyChipActive() {
        return (this._filterDomains.length > 0 ||
            this._filterAreas.length > 0 ||
            this._filterDeviceClasses.length > 0 ||
            this._filterDetectors.length > 0 ||
            this._filterFloors.length > 0 ||
            this._filterIntegrations.length > 0 ||
            this._filterLabels.length > 0);
    }
    _clearChipFilters() {
        this._filterDomains = [];
        this._filterAreas = [];
        this._filterDeviceClasses = [];
        this._filterDetectors = [];
        this._filterFloors = [];
        this._filterIntegrations = [];
        this._filterLabels = [];
    }
    /** A row of small chips listing each detector and its insight count.
     *  Clicking a chip toggles that detector into / out of the detector
     *  filter — fastest way to "show me only the cooccurrence ones". The
     *  active chip is visually emphasized so you can tell what's filtered. */
    _renderRollupProgress() {
        const p = this._rollupProgress;
        const rec = this._recorderStatus;
        // Always render the recorder-window hint row when we have it so
        // users can see what window the rollup will actually fill — even
        // when no batch is in flight.
        let hint = "";
        if (rec) {
            const cfg = rec.configured_audit_window_days;
            const eff = rec.effective_window_days;
            const keep = rec.purge_keep_days;
            const clamped = cfg !== null && eff !== null && eff < cfg;
            hint = b `<div class="rollup-hint">
        ${cfg !== null
                ? b `Audit window: <strong>${cfg}</strong> days configured`
                : ""}
        ${keep !== null
                ? b ` · recorder keeps <strong>${keep}</strong> days`
                : ""}
        ${rec.oldest_record_age_days !== null
                ? b ` · oldest row
              <strong>${rec.oldest_record_age_days}</strong> days ago`
                : ""}
        ${eff !== null
                ? b ` · <span class=${clamped ? "rollup-hint-warn" : ""}
              >effective <strong>${eff}</strong> days${clamped
                    ? " (limited by recorder)"
                    : ""}</span
            >`
                : ""}
        ${clamped
                ? b `<div class="rollup-hint-tip">
              <strong>Good news:</strong> v1.2 incremental rollup is
              active — once a day is rolled up, its bucket counts
              are kept in HA Insights' own SQLite and
              <em>survive recorder purges</em>. You don't need to
              keep a huge recorder DB to build long-term seasonal
              patterns. Enable
              <code>Auto-refresh audit rollups every 6h</code> in
              Configure and the buckets accumulate over time. The
              effective window above is what's available
              <em>right now</em> for first-time backfill.
              ${keep !== null && keep < 30
                    ? b ` Default HA recorder retains
                    <strong>${keep}</strong> days — bumping
                    <code>recorder.purge_keep_days</code> in
                    <code>configuration.yaml</code> speeds up the
                    initial backfill but isn't required long term.`
                    : ""}
            </div>`
                : ""}
      </div>`;
        }
        if (!p || (!p.running && !p.last_summary)) {
            return hint
                ? b `<div class="rollup-row">${hint}</div>`
                : "";
        }
        const pct = p.total > 0 ? Math.min(100, Math.round((p.processed / p.total) * 100)) : 0;
        const eta = p.eta_sec !== undefined && p.running
            ? ` · ETA ${this._formatSec(p.eta_sec)}`
            : "";
        const summary = p.running
            ? b `<span class="rollup-stat">
          ${p.processed}/${p.total} (${pct}%) · ${p.window_days}d window${eta}
          ${p.current_entity_id
                ? b ` · <code>${p.current_entity_id}</code>`
                : ""}
          ${p.errors ? b ` · ${p.errors} err` : ""}
          ${p.timed_out ? b ` · ${p.timed_out} timeout` : ""}
        </span>`
            : b `<span class="rollup-stat rollup-stat-done">
          Last run: ${p.processed} done${p.errors ? `, ${p.errors} err` : ""}${p.timed_out ? `, ${p.timed_out} timeout` : ""}
        </span>`;
        return b `<div class="rollup-row">
      <div class="rollup-bar-wrap">
        <div class="rollup-bar">
          <div
            class="rollup-bar-fill ${p.running ? "is-running" : "is-done"}"
            style="width: ${p.running ? pct : 100}%"
          ></div>
        </div>
        ${summary}
      </div>
      ${hint}
    </div>`;
    }
    _formatSec(s) {
        if (s < 60)
            return `${Math.round(s)}s`;
        const m = Math.floor(s / 60);
        const r = Math.round(s % 60);
        return r ? `${m}m ${r}s` : `${m}m`;
    }
    _renderDetectorCounts() {
        const detectors = Object.keys(this._detectorCounts);
        if (detectors.length === 0)
            return "";
        const active = new Set(this._filterDetectors);
        // Order by count descending so the noisiest detectors land first.
        detectors.sort((a, b) => (this._detectorCounts[b] ?? 0) - (this._detectorCounts[a] ?? 0));
        return b `<div class="detector-counts">
      ${detectors.map((d) => {
            const count = this._detectorCounts[d] ?? 0;
            const isActive = active.has(d);
            return b `<button
          class="detector-chip ${isActive ? "is-active" : ""}"
          title=${isActive
                ? `Showing only ${d} insights — click to clear`
                : `Filter to ${d} insights only`}
          @click=${() => this._toggleDetectorChip(d)}
        >
          ${d}<span class="detector-chip-count">${count}</span>
        </button>`;
        })}
    </div>`;
    }
    _toggleDetectorChip(detector) {
        const active = new Set(this._filterDetectors);
        if (active.has(detector)) {
            active.delete(detector);
        }
        else {
            active.add(detector);
        }
        this._filterDetectors = Array.from(active);
    }
    /** Render a row of multi-select dropdowns for each filter axis.
     *  Each option list is built from the distinct values in the currently-
     *  loaded insight set so we never offer a filter that returns empty
     *  results. Area + Floor use registry display names when available so
     *  the user sees "Kitchen" instead of "kitchen_3a8b…". */
    _renderChipFilters() {
        const renderSelect = (label, values, selected, onChange, labelFor) => {
            if (values.length === 0)
                return "";
            return b `<select
        aria-label=${label}
        multiple
        size="1"
        style="min-width:110px;"
        @change=${(e) => {
                const select = e.target;
                const picked = Array.from(select.selectedOptions).map((o) => o.value);
                onChange(picked);
            }}
      >
        <option value="" ?selected=${selected.length === 0}>
          ${label}: All
        </option>
        ${values.map((v) => b `<option value=${v} ?selected=${selected.includes(v)}>
              ${labelFor ? labelFor(v) : v}
            </option>`)}
      </select>`;
        };
        return b `<div class="filters" style="padding-top:0;">
      ${renderSelect("Domain", this._availableDomains, this._filterDomains, (n) => (this._filterDomains = n))}
      ${renderSelect("Area", this._availableAreas, this._filterAreas, (n) => (this._filterAreas = n), (id) => this._areaNameById[id] ?? id)}
      ${renderSelect("Floor", this._availableFloors, this._filterFloors, (n) => (this._filterFloors = n), (id) => this._floorNameById[id] ?? id)}
      ${renderSelect("Integration", this._availableIntegrations, this._filterIntegrations, (n) => (this._filterIntegrations = n))}
      ${this._availableLabels.length > 0
            ? renderSelect("Label", this._availableLabels, this._filterLabels, (n) => (this._filterLabels = n))
            : A}
      ${renderSelect("Device class", this._availableDeviceClasses, this._filterDeviceClasses, (n) => (this._filterDeviceClasses = n))}
      ${renderSelect("Detector", this._availableDetectors, this._filterDetectors, (n) => (this._filterDetectors = n))}
    </div>`;
    }
    _renderCard() {
        // Declarative binding so Lit reuses the SAME card element across panel
        // re-renders. Earlier we created the element imperatively each render,
        // which destroyed the card's internal state mid-refine (modal closed,
        // result discarded). Lit's html template diffs by tag + position; same
        // tag in the same slot = same element preserved.
        // v1.3.4: use the panel-bundled alias (ha-insights-card-bundled)
        // so the panel ALWAYS uses the freshly-built class from this
        // bundle — never a stale HACS-installed ha-insights-card that
        // claimed the element name first.
        return b `
      <ha-insights-card-bundled
        .hass=${this.hass}
        .config=${this._embeddedCardConfig}
      ></ha-insights-card-bundled>
    `;
    }
}
__decorate([
    n({ attribute: false })
], HaInsightsPanel.prototype, "hass", void 0);
__decorate([
    n({ type: Boolean })
], HaInsightsPanel.prototype, "narrow", void 0);
__decorate([
    n({ attribute: false })
], HaInsightsPanel.prototype, "route", void 0);
__decorate([
    n({ attribute: false })
], HaInsightsPanel.prototype, "panel", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_search", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_minConfidence", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_sortBy", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_groupBy", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_hideAlreadyAutomated", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_backfillBusy", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_bulkBusy", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_scanBusy", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_rollupBusy", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_rollupProgress", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_recorderStatus", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_filterDomains", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_filterAreas", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_filterDeviceClasses", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_filterDetectors", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_filterFloors", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_filterIntegrations", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_filterLabels", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_auditDepth", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_totalInsightCount", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_visibleInsightCount", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_diagnosticsJson", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_diagnosticsBusy", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_findDeviceOpen", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_findDeviceSearch", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_findDeviceSelected", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_findDeviceCount", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_findDeviceErrors", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_findDeviceFireCounts", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_findDeviceSessionElapsedMs", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_availableDomains", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_availableAreas", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_availableDeviceClasses", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_availableDetectors", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_availableFloors", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_availableIntegrations", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_availableLabels", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_areaNameById", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_floorNameById", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_detectorCounts", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_toast", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_auditOpen", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_auditLog", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_auditBusy", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_findDeviceWatchBaselines", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_findDeviceWatchCurrent", void 0);
__decorate([
    r()
], HaInsightsPanel.prototype, "_findDeviceWatchDetected", void 0);
// Guard against double-registration — only relevant if a future Lovelace
// resource ever imports this bundle directly (today only the integration
// auto-registers it). Cheap to be safe.
if (!customElements.get("ha-insights-panel")) {
    customElements.define("ha-insights-panel", HaInsightsPanel);
}
// v1.3.1: HA panel-mount recovery — fixes the v1.2.26 observer-scope bug.
//
// Background: v1.2.26 added a MutationObserver scoped to `document.body`,
// intending to detect when HA's `<ha-panel-custom>` wrapper ended up empty
// (either because `panel.config` was lost OR because an `AbortError:
// Transition was skipped` interrupted the mount).
//
// **The bug**: MutationObservers do NOT cross shadow-root boundaries.
// `<ha-panel-custom>` is rendered inside `<home-assistant-main>`'s shadow
// root, never in `document.body`. So the v1.2.26 observer fired on
// unrelated mutations but never on the one mutation that mattered (the
// wrapper being inserted into HA's main shadow root).
//
// Result on user installs: the v1.2.26 initial `tryRecover()` call helped
// in the rare case where the wrapper already existed at module load
// (e.g., navigating back to /ha-insights after a previous visit in the
// same session). But on first navigation post page-load, the wrapper
// hadn't been inserted yet → initial call returned early → observer
// never fired → blank panel persisted until hard refresh.
//
// **v1.3.1 fixes**:
// 1. Observe `home-assistant-main`'s shadowRoot directly once it exists
//    (with a fallback poller for the brief window before HA mounts main).
// 2. Listen for URL changes (popstate + hashchange + a wrapped pushState)
//    so we also try right after every navigation.
// 3. Add a short setInterval backstop for the first 5 seconds after each
//    URL change — covers the AbortError race where HA inserts the
//    wrapper but its mount fails silently.
// 4. Diagnostic counter on `window.__haInsightsPanelRecovery` so future
//    blank-panel reports include "recovery attempted N times".
//
// All idempotent. Scoped to our route only. Zero behavior change when
// HA's mount works correctly.
(function installPanelMountRecovery() {
    const RECOVERY_KEY = "__haInsightsPanelRecovery";
    const win = window;
    if (win[RECOVERY_KEY] && win[RECOVERY_KEY].installed) {
        return; // already installed in this page session
    }
    const state = {
        installed: true,
        attempts: 0,
        forcedMounts: 0,
        lastAttemptAt: 0,
    };
    win[RECOVERY_KEY] = state;
    const findWrapper = () => {
        const ha = document.querySelector("home-assistant");
        const main = ha?.shadowRoot?.querySelector("home-assistant-main");
        return main?.shadowRoot?.querySelector("ha-panel-custom")
            ?? null;
    };
    const onRoute = () => {
        return window.location.pathname.startsWith("/ha-insights");
    };
    // v1.3.3: dedupe pass. If two ha-insights-panel ended up siblings
    // (HA's normal resolver + our recovery both fired), keep the first
    // and remove the rest. Idempotent.
    const dedupePanels = (wrap) => {
        const panels = wrap.querySelectorAll("ha-insights-panel");
        if (panels.length <= 1)
            return 0;
        let removed = 0;
        for (let i = 1; i < panels.length; i++) {
            panels[i].remove();
            removed += 1;
        }
        // eslint-disable-next-line no-console
        console.info(`[ha-insights] removed ${removed} duplicate panel element(s)`);
        return removed;
    };
    // v1.3.5: gate the actual force-mount behind a 600ms grace timer.
    //
    // Why: HA's `<ha-panel-custom>._createPanel` dynamically imports the
    // module and only appends the panel element AFTER the import resolves
    // (~10–50ms on a warm cache). Our `mainObserver` fires the instant HA
    // inserts the empty `<ha-panel-custom>` wrapper into the main shadow
    // root — at which point the wrapper has 0 children because HA's
    // import `.then` hasn't run yet. v1.3.4 tryRecover would observe the
    // empty wrapper and force-mount immediately, then HA's `.then` would
    // append a second copy ~15ms later, which dedupe would clean up.
    // forcedMounts incremented spuriously on every nav even though HA's
    // mount was working.
    //
    // 600ms grace is comfortably above HA's typical mount latency on a
    // warm cache and matches the spirit of the existing 500ms burstOnNav
    // delay. If HA succeeds in the grace window, the deferred check sees
    // a non-empty wrapper and no-ops. If HA genuinely fails, the deferred
    // check force-mounts as before.
    let pendingRecoveryTimer = null;
    const MOUNT_GRACE_MS = 600;
    const tryRecover = () => {
        state.attempts += 1;
        state.lastAttemptAt = Date.now();
        if (!onRoute())
            return;
        const wrap = findWrapper();
        if (!wrap)
            return;
        // v1.3.3: always dedupe first. If HA's resolver mounted alongside
        // our recovery (race), clean up before deciding whether to mount.
        dedupePanels(wrap);
        if (wrap.querySelector("ha-insights-panel"))
            return;
        if (!customElements.get("ha-insights-panel"))
            return;
        // Wrapper is empty. Schedule a deferred re-check rather than
        // force-mounting immediately. Idempotent: a pending timer absorbs
        // additional observer hits for the same empty window.
        if (pendingRecoveryTimer !== null)
            return;
        pendingRecoveryTimer = window.setTimeout(() => {
            pendingRecoveryTimer = null;
            if (!onRoute())
                return;
            const w = findWrapper();
            if (!w)
                return;
            dedupePanels(w);
            if (w.querySelector("ha-insights-panel"))
                return; // HA succeeded
            if (!customElements.get("ha-insights-panel"))
                return;
            const el = document.createElement("ha-insights-panel");
            el.hass = w.hass;
            el.narrow = w.narrow;
            el.panel = w.panel;
            w.appendChild(el);
            state.forcedMounts += 1;
            // Single console line so users sending diagnostics can see we
            // recovered (and how often). Intentionally not behind a debug
            // flag — forced-mount counts are useful evidence in future bug
            // reports.
            // eslint-disable-next-line no-console
            console.info("[ha-insights] panel mount recovered (forced-mount #"
                + `${state.forcedMounts}, attempts=${state.attempts})`);
        }, MOUNT_GRACE_MS);
    };
    // Watch the right shadow root — the one HA actually mutates when it
    // inserts ha-panel-custom. The v1.2.26 observer on document.body
    // could not see this mutation; cross-shadow-boundary observation
    // is not supported by the MutationObserver spec.
    let mainObserver = null;
    const attachShadowObserver = () => {
        if (mainObserver)
            return;
        const ha = document.querySelector("home-assistant");
        const main = ha?.shadowRoot?.querySelector("home-assistant-main");
        const shadow = main?.shadowRoot;
        if (!shadow)
            return;
        mainObserver = new MutationObserver(() => tryRecover());
        mainObserver.observe(shadow, { childList: true, subtree: true });
    };
    // The home-assistant-main shadow root may not exist at module load.
    // Poll briefly until it does, then stop. (Bounded — gives up after
    // 30s; production HA mounts main in <2s on any healthy install.)
    const start = Date.now();
    const shadowPoller = window.setInterval(() => {
        if (mainObserver || Date.now() - start > 30_000) {
            window.clearInterval(shadowPoller);
            return;
        }
        attachShadowObserver();
    }, 250);
    // On URL change → one tryRecover. v1.3.5: tryRecover now self-gates
    // with a 600ms grace timer, so we no longer need the 5s × 250ms
    // polling burst. A single call schedules the deferred check; if HA's
    // normal mount succeeds in the grace window, the deferred check
    // no-ops. The mainObserver covers the case where HA mounts the
    // wrapper after this nav event but before our deferred check fires.
    const burstOnNav = () => {
        if (!onRoute())
            return;
        tryRecover();
    };
    // Wrap history.pushState so we hear about programmatic navigation
    // (HA uses Vaadin Router which calls pushState; vanilla popstate
    // alone misses these).
    const origPush = window.history.pushState.bind(window.history);
    window.history.pushState = function (...args) {
        const result = origPush(...args);
        window.dispatchEvent(new Event("ha-insights:navigated"));
        return result;
    };
    window.addEventListener("ha-insights:navigated", burstOnNav);
    window.addEventListener("popstate", burstOnNav);
    window.addEventListener("hashchange", burstOnNav);
    // v1.3.3: skip the immediate-at-module-load tryRecover() (v1.3.1
    // ran one synchronously, which raced HA's normal mount on the very
    // first /ha-insights visit and produced two stacked panels). The
    // burst starts immediately but its first probe is delayed 500ms,
    // giving HA the chance to mount normally. If HA succeeds, the
    // dedupe + early-return guard skip our mount entirely. If HA
    // fails, recovery kicks in after the delay.
    burstOnNav();
})();

export { HaInsightsPanel };
//# sourceMappingURL=ha-insights-panel.js.map
