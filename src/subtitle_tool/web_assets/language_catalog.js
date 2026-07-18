window.subtitleLanguageCatalog = (() => {
  const cloudLanguages = [
    ["zh-CN", "中文"], ["zh-TW", "繁中"], ["en", "英语"], ["ja", "日语"],
    ["ko", "韩语"], ["fr", "法语"], ["de", "德语"], ["es", "西班牙语"],
    ["pt", "葡萄牙语"], ["it", "意大利语"], ["ru", "俄语"], ["ar", "阿拉伯语"],
    ["th", "泰语"], ["vi", "越南语"], ["id", "印尼语"], ["tr", "土耳其语"],
    ["nl", "荷兰语"], ["pl", "波兰语"], ["uk", "乌克兰语"], ["hi", "印地语"],
    ["ms", "马来语"], ["sv", "瑞典语"], ["el", "希腊语"], ["he", "希伯来语"],
    ["fa", "波斯语"], ["cs", "捷克语"], ["ro", "罗马尼亚语"], ["hu", "匈牙利语"],
    ["fi", "芬兰语"], ["da", "丹麦语"], ["no", "挪威语"], ["sk", "斯洛伐克语"],
    ["bg", "保加利亚语"], ["hr", "克罗地亚语"], ["sr", "塞尔维亚语"], ["sl", "斯洛文尼亚语"],
    ["lt", "立陶宛语"], ["lv", "拉脱维亚语"], ["et", "爱沙尼亚语"], ["bn", "孟加拉语"],
    ["ur", "乌尔都语"], ["ta", "泰米尔语"], ["te", "泰卢固语"], ["sw", "斯瓦希里语"],
  ];
  const fastLocalLanguages = [["zh-CN", "中文"], ["ja", "日语"], ["en", "英语"]];
  const nllbLanguages = [
    ["zh-CN", "中文"], ["zh-TW", "繁中"], ["en", "英语"], ["ja", "日语"],
    ["ko", "韩语"], ["fr", "法语"], ["de", "德语"], ["es", "西班牙语"],
    ["pt", "葡萄牙语"], ["it", "意大利语"], ["ru", "俄语"], ["ar", "阿拉伯语"],
    ["th", "泰语"], ["vi", "越南语"], ["id", "印尼语"],
  ];

  return {
    languagePickerModes: {
      "local-transformer": {
        languages: fastLocalLanguages,
        allowCustom: false,
        hint: "本地快速模型只建议选择中文、日语、英语；更多语言请切换 z.ai、OpenAI 或 NLLB。",
      },
      "local-nllb": {
        languages: nllbLanguages,
        allowCustom: false,
        hint: "旧任务兼容模式，实际使用 NLLB 1.3B；异常字幕会自动单句重试。",
      },
      "local-nllb-quality": {
        languages: nllbLanguages,
        allowCustom: false,
        hint: "NLLB 1.3B 覆盖更多本地语言，质量优先；异常字幕会自动单句重试。",
      },
      "z-ai": {
        languages: cloudLanguages,
        allowCustom: true,
        hint: "z.ai 适合多语言翻译；快捷按钮只是常用语言，也可以手动填写其它语言代码。",
      },
      openai: {
        languages: cloudLanguages,
        allowCustom: true,
        hint: "OpenAI 适合多语言高质量翻译；快捷按钮只是常用语言，也可以手动填写其它语言代码。",
      },
    },
  };
})();
