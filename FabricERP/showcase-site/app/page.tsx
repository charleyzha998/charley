"use client";

import { FormEvent, useEffect, useState } from "react";

type Language = "en" | "zh";

const copy = {
  en: {
    nav: [
      ["Products", "#products"],
      ["Capabilities", "#capabilities"],
      ["About", "#about"],
      ["Contact", "#contact"],
    ],
    eyebrow: "22 MOMME SILK · CUSTOM MANUFACTURING",
    title: "Silk essentials,\nmade beautifully.",
    intro:
      "From pillowcases and sleep masks to pouches and accessories, we turn premium silk into thoughtful products for modern brands.",
    primary: "Explore products",
    secondary: "Request a quote",
    stats: ["100% Mulberry Silk", "Flexible order quantities", "Custom color & packaging"],
    collectionTag: "OUR COLLECTION",
    collectionTitle: "Made for rest, beauty and gifting",
    collectionIntro:
      "A focused range of silk essentials and fabric packaging, ready for private-label development.",
    products: [
      ["Silk Pillowcases", "22 momme silk satin", "40×60 · 50×70 · 70×90 cm", "/products/generated-pillow-v1.png"],
      ["Silk Sleep Masks", "Soft and light-blocking", "Custom filling, piping and straps", "/products/generated-eye-mask-v1.png"],
      ["Pouches & Packaging", "Silk and cotton options", "Custom size, ribbon and logo", "/products/generated-pouches-v1.png"],
      ["Silk Scrunchies", "Multiple fabric widths", "1 · 2 · 4.5 cm and custom", "/products/generated-scrunchies-v1.png"],
      ["Silk Bonnets", "Comfortable hair protection", "Custom shape, fit and color", "/products/generated-bonnet-v1.png"],
      ["Silk Sleepwear", "Product development service", "Sampling and size-set support", "/products/generated-sleepwear-v1.png"],
    ],
    capabilityTag: "WHAT WE DO",
    capabilityTitle: "From silk fabric to a shelf-ready product.",
    capabilities: [
      ["Material sourcing", "22 momme and custom-weight silk fabrics with color matching and finishing support."],
      ["Product development", "Pattern, sample, size and construction refinement for new private-label products."],
      ["Brand details", "Woven labels, care labels, printed logos, ribbons and packaging developed as one system."],
      ["Quality control", "In-line and final checks covering color, measurement, stitching, labels and packing."],
    ],
    materialLabel: "CORE MATERIAL",
    materialTitle: "22 momme silk satin",
    materialBody:
      "Smooth, luminous and durable enough for everyday sleep products. Selected fabric samples have passed requested tests for color fastness, pilling resistance and seam slippage.",
    materialFacts: [
      ["Composition", "100% mulberry silk"],
      ["Construction", "Woven silk satin"],
      ["Origin", "Shengze, Suzhou, China"],
      ["Customisation", "Color, weight and finish"],
    ],
    aboutTag: "ABOUT PUJUN",
    aboutTitle: "A practical silk manufacturing partner in Suzhou.",
    aboutBody:
      "We support international brands with silk product sourcing, sampling, production and export preparation. Our work combines local textile supply-chain access with careful handling of the small details that make a branded product feel complete.",
    processTitle: "A clear path from idea to shipment",
    steps: [
      ["01", "Brief & quotation", "Share the product, material, quantity and packaging requirements."],
      ["02", "Sampling", "Confirm color, construction, dimensions, labels and packing."],
      ["03", "Production & QC", "Bulk production with in-line checks and final inspection."],
      ["04", "Packing & export", "Carton packing, documentation and shipment coordination."],
    ],
    contactTag: "START A PROJECT",
    contactTitle: "Tell us what you would like to make.",
    contactBody:
      "Send a reference image, target quantity and preferred material. We will help turn it into a clear sampling and quotation plan.",
    contactCompany: "Suzhou Pujun Textile Co., Ltd.",
    contactAddress: "Shengze, Wujiang, Suzhou, Jiangsu, China",
    phoneLabel: "TEL",
    emailLabel: "EMAIL / WHATSAPP",
    emailValue: "Add contact before publishing",
    form: ["Name / Company", "Email", "Product of interest", "Target quantity", "Tell us about your project"],
    submit: "Send inquiry",
    sent: "Prototype form received. Connect your business inbox before publishing.",
    footer: "Custom silk products · Private label · Export support",
  },
  zh: {
    nav: [
      ["产品", "#products"],
      ["定制能力", "#capabilities"],
      ["关于我们", "#about"],
      ["联系询价", "#contact"],
    ],
    eyebrow: "22姆米真丝 · 支持定制生产",
    title: "把真丝，做成\n更美好的日常。",
    intro:
      "从枕套、眼罩到收纳袋和真丝配饰，我们为品牌客户提供产品开发、生产及定制包装服务。",
    primary: "查看产品",
    secondary: "获取报价",
    stats: ["100%桑蚕丝", "灵活起订数量", "颜色与包装定制"],
    collectionTag: "产品系列",
    collectionTitle: "为睡眠、美护与礼赠而设计",
    collectionIntro: "聚焦实用而精致的真丝产品及布艺包装，支持品牌定制开发。",
    products: [
      ["真丝枕套", "22姆米真丝缎", "40×60 · 50×70 · 70×90厘米", "/products/generated-pillow-v1.png"],
      ["真丝眼罩", "亲肤柔软、舒适遮光", "填充、包边和松紧带可定制", "/products/generated-eye-mask-v1.png"],
      ["收纳袋与包装", "真丝及全棉材质", "尺寸、织带与Logo定制", "/products/generated-pouches-v1.png"],
      ["真丝发圈", "多种面料宽度", "1 · 2 · 4.5厘米及定制规格", "/products/generated-scrunchies-v1.png"],
      ["真丝睡帽", "舒适护发", "版型、尺寸及颜色可定制", "/products/generated-bonnet-v1.png"],
      ["真丝睡衣", "新品开发服务", "支持打样及尺码套样", "/products/generated-sleepwear-v1.png"],
    ],
    capabilityTag: "我们的能力",
    capabilityTitle: "从真丝面料到可以上架销售的成品。",
    capabilities: [
      ["面料供应", "提供22姆米及不同克重真丝，支持配色、染色和后整理。"],
      ["产品开发", "为品牌新品提供纸样、样品、尺码和工艺结构调整。"],
      ["品牌细节", "织唛、洗唛、Logo印刷、织带与包装统一开发。"],
      ["品质管理", "从生产过程到成品，对颜色、尺寸、缝制、标签和包装进行检查。"],
    ],
    materialLabel: "核心面料",
    materialTitle: "22姆米真丝缎",
    materialBody:
      "光泽细腻、手感顺滑，也具有适合日常睡眠用品的耐用度。选定面料样品已通过客户要求的色牢度、抗起球及接缝滑移测试。",
    materialFacts: [
      ["成分", "100%桑蚕丝"],
      ["组织", "梭织真丝缎"],
      ["产地", "中国苏州盛泽"],
      ["定制", "颜色、姆米数及后整理"],
    ],
    aboutTag: "关于普骏",
    aboutTitle: "位于苏州的务实型真丝产品制造伙伴。",
    aboutBody:
      "我们为海外品牌提供真丝产品选材、打样、生产及出口配套服务。依托盛泽纺织供应链，同时关注标签方向、尺寸、车缝和包装等决定品牌质感的细节。",
    processTitle: "从想法到出货，流程清晰",
    steps: [
      ["01", "需求与报价", "提供产品、材质、数量和包装要求。"],
      ["02", "打样确认", "确认颜色、结构、尺寸、标签和包装。"],
      ["03", "生产与质检", "大货生产，并进行过程检查和成品检验。"],
      ["04", "包装与出口", "装箱、单据准备及运输协调。"],
    ],
    contactTag: "开始一个项目",
    contactTitle: "告诉我们，你想做什么产品。",
    contactBody: "发送参考图片、目标数量和面料要求，我们会整理打样及报价方案。",
    contactCompany: "苏州市普骏纺织有限公司",
    contactAddress: "中国江苏省苏州市吴江区盛泽镇",
    phoneLabel: "电话",
    emailLabel: "邮箱 / WhatsApp",
    emailValue: "发布前补充联系方式",
    form: ["姓名 / 公司", "邮箱", "感兴趣的产品", "目标数量", "请简单描述您的项目"],
    submit: "提交询价",
    sent: "演示询价已收到。正式发布前需要接入业务邮箱。",
    footer: "真丝产品定制 · 品牌代工 · 出口配套",
  },
} as const;

export default function Home() {
  const [language, setLanguage] = useState<Language>("en");
  const [sent, setSent] = useState(false);
  const t = copy[language];

  useEffect(() => {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  }, [language]);

  function submitInquiry(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSent(true);
  }

  return (
    <main>
      <header className="siteHeader">
        <a className="brand" href="#top" aria-label="Pujun Silk home">
          <span className="brandMark">P</span>
          <span>PUJUN SILK<small>普骏丝绸</small></span>
        </a>
        <nav aria-label="Main navigation">
          {t.nav.map(([item, href]) => <a key={item} href={href}>{item}</a>)}
        </nav>
        <div className="languageSwitch" aria-label="Language switcher">
          <button className={language === "en" ? "active" : ""} onClick={() => setLanguage("en")}>EN</button>
          <span>/</span>
          <button className={language === "zh" ? "active" : ""} onClick={() => setLanguage("zh")}>中文</button>
        </div>
      </header>

      <section className="hero" id="top">
        <div className="heroCopy">
          <p className="eyebrow">{t.eyebrow}</p>
          <h1>{t.title}</h1>
          <p className="heroIntro">{t.intro}</p>
          <div className="heroActions">
            <a className="button dark" href="#products">{t.primary}</a>
            <a className="button light" href="#contact">{t.secondary}</a>
          </div>
          <div className="heroStats">
            {t.stats.map((stat, index) => <div key={stat}><span>0{index + 1}</span>{stat}</div>)}
          </div>
        </div>
        <div className="heroVisual">
          <div className="imageFrame">
            <img src="/products/generated-pillow-v1.png" alt="Champagne silk pillowcase in a warm studio setting" />
          </div>
          <p className="verticalNote">PRIVATE LABEL · SILK GOODS · SUZHOU</p>
        </div>
      </section>

      <section className="collection" id="products">
        <div className="sectionHeading">
          <div><p className="eyebrow">{t.collectionTag}</p><h2>{t.collectionTitle}</h2></div>
          <p>{t.collectionIntro}</p>
        </div>
        <div className="productGrid">
          {t.products.map(([name, description, spec, image], index) => (
            <article className="productCard" key={name}>
              <div className="productImage"><img src={image} alt={name} /></div>
              <div className="productInfo">
                <span>0{index + 1}</span>
                <div><h3>{name}</h3><p>{description}</p><small>{spec}</small></div>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="capabilities" id="capabilities">
        <div className="capabilityIntro">
          <p className="eyebrow">{t.capabilityTag}</p>
          <h2>{t.capabilityTitle}</h2>
        </div>
        <div className="capabilityList">
          {t.capabilities.map(([title, body], index) => (
            <article key={title}><span>0{index + 1}</span><h3>{title}</h3><p>{body}</p></article>
          ))}
        </div>
      </section>

      <section className="material">
        <div className="materialImage"><img src="/products/silk-fabric.jpg" alt="22 momme silk satin fabric" /></div>
        <div className="materialCopy">
          <p className="eyebrow">{t.materialLabel}</p>
          <h2>{t.materialTitle}</h2>
          <p className="largeBody">{t.materialBody}</p>
          <dl>
            {t.materialFacts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
          </dl>
        </div>
      </section>

      <section className="about" id="about">
        <div className="aboutStatement">
          <p className="eyebrow">{t.aboutTag}</p>
          <h2>{t.aboutTitle}</h2>
          <p>{t.aboutBody}</p>
        </div>
        <div className="process">
          <h3>{t.processTitle}</h3>
          {t.steps.map(([number, title, body]) => (
            <div className="processStep" key={number}><span>{number}</span><h4>{title}</h4><p>{body}</p></div>
          ))}
        </div>
      </section>

      <section className="contact" id="contact">
        <div className="contactCopy">
          <p className="eyebrow">{t.contactTag}</p>
          <h2>{t.contactTitle}</h2>
          <p>{t.contactBody}</p>
          <address>
            <strong>{t.contactCompany}</strong>
            <span>{t.contactAddress}</span>
            <span><small>{t.phoneLabel}</small> +86 512 6355 1388</span>
            <span><small>{t.emailLabel}</small> {t.emailValue}</span>
          </address>
        </div>
        <form className="inquiryForm" onSubmit={submitInquiry}>
          <div className="formRow"><label>{t.form[0]}<input required name="name" /></label><label>{t.form[1]}<input required type="email" name="email" /></label></div>
          <div className="formRow"><label>{t.form[2]}<input name="product" /></label><label>{t.form[3]}<input name="quantity" /></label></div>
          <label>{t.form[4]}<textarea required name="message" rows={5} /></label>
          <button className="button dark" type="submit">{t.submit}<span>↗</span></button>
          {sent && <p className="formNotice" role="status">{t.sent}</p>}
        </form>
      </section>

      <footer>
        <a className="brand" href="#top"><span className="brandMark">P</span><span>PUJUN SILK<small>普骏丝绸</small></span></a>
        <p>{t.footer}</p><p>© 2026 PUJUN SILK</p>
      </footer>
    </main>
  );
}
