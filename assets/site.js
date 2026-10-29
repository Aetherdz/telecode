'use strict';
const root = document.documentElement;
const themeButton = document.querySelector('#theme-toggle');
const languageButton = document.querySelector('#language-toggle');
const navToggle = document.querySelector('.nav-toggle');
const nav = document.querySelector('#nav');
const preview = document.querySelector('#model-preview');
try {
  const savedTheme = localStorage.getItem('telecode-theme');
  if (!savedTheme && matchMedia('(prefers-color-scheme: dark)').matches) root.dataset.theme = 'dark';
} catch (_) {}
let previewState = { type: 'provider', value: document.querySelector('.provider.selected')?.dataset.provider || '' };

const messages = {
  en: {
    pageTitle: 'TeleCode — your coding sessions, within reach',
    metaDescription: 'TeleCode connects Telegram to local OpenCode sessions and coding-agent MCP tools.',
    skip: 'Skip to content', homeAria: 'TeleCode home', repositoryLink: 'Aetherdz / TeleCode', repositoryAria: 'TeleCode repository on GitHub (opens in a new tab)', navOpen: 'Open navigation', navClose: 'Close navigation', mainNav: 'Main navigation',
    switchLanguageAria: 'Switch language to Arabic', phonePreview: 'Illustrative model picker preview', switchTheme: 'Switch color theme',
    themeToDarkAria: 'Switch to dark mode', themeToLightAria: 'Switch to light mode',
    providerAria: 'Choose {provider} as the model provider', previewButtonAria: '{action} preview',
    navFlow: 'How it works', navIntegrations: 'Integrations', navCommands: 'Commands', navSecurity: 'Security', navInstall: 'Install',
    switchLanguage: 'العربية', darkMode: 'Dark mode', lightMode: 'Light mode',
    heroEyebrow: 'TELEGRAM TO LOCAL SESSIONS', heroTitle: 'Your coding session,<br><em>within reach.</em>',
    heroLede: 'Choose an OpenCode session, message it from Telegram, and receive replies through local MCP tools.',
    getStarted: 'Get started', viewSource: 'View source', selectedTarget: 'Selected target: OpenCode session',
    localListener: 'Local listener', pythonVersion: 'Python 3.11+', stdlib: 'Standard library', mitLicense: 'MIT license', github: 'GitHub',
    mapTitle: 'TeleCode message routing', mapDesc: 'A Telegram owner chat routes messages through the local bridge to a selected OpenCode session, then receives agent replies through MCP tools.',
    mapOwner: 'OWNER CHAT', mapBridge: 'LOCAL BRIDGE', mapCheck: 'OWNER CHECK · ROUTE', mapSession: 'SELECTED SESSION', mapRoute: 'LOCAL ROUTE / 01', mapReply: 'MCP REPLY ↗',
    loopEyebrow: '01 / THE LOOP', loopTitle: 'One owner.<br>One clear route.',
    step1Title: 'Connect your bot', step1Text: 'Configure the owner chat and run the listener locally. It accepts only authorized updates.',
    step2Title: 'Choose a session', step2Text: 'Pick a named OpenCode session. Incoming messages go to that active target.',
    step3Title: 'Keep working', step3Text: 'Send requests in Telegram. The agent can reply through MCP and return allowlisted files.',
    capEyebrow: '02 / CAPABILITIES', capTitle: 'Purpose-built, not a remote shell.',
    cap1Title: 'Named session routing', cap1Text: 'Browse sessions by title, navigate pages, and switch the active target explicitly.',
    cap2Title: 'Model selection', cap2Text: 'Browse providers and models in Telegram, then update the active OpenCode session.',
    cap3Title: 'File exchange', cap3Text: 'Route incoming attachments to their captured session and restrict outbound files to approved roots.',
    cap4Title: 'MCP replies', cap4Text: 'Local coding-agent clients can use bridge tools to send text, files, and session status.',
    cap5Title: 'Owner checks', cap5Text: 'Chat identity is checked before routing; sender identity is checked when Telegram provides it.',
    cap6Title: 'Local operation', cap6Text: 'No public webhook or hosted broker. Optional systemd user service starts the listener.',
    showEyebrow: '03 / TELEGRAM INTERFACE', showTitle: 'A small control surface for real work.',
    showText: 'Pick a session, inspect the active target, or change its model without switching to a browser dashboard.',
    kbLabel: 'Telegram keyboard options', kbSessions: 'Sessions', kbCurrent: 'Current session', kbModels: 'Models', kbHelp: 'Help',
    previewLabel: 'MODEL PICKER PREVIEW', providerTitle: 'CHOOSE A MODEL PROVIDER', preview: 'PREVIEW', chooseProvider: 'Choose a provider',
    previous: 'Previous', next: 'Next', providers: 'Providers', close: 'Close',
    intEyebrow: '04 / INTEGRATIONS', intTitle: 'Clear support boundaries.', tableCaption: 'Coding-agent integration support',
    intText: 'OpenCode has targeted Telegram-to-session routing. Other listed clients can use outbound MCP tools where their configuration supports them.',
    opencode: 'OpenCode', claudeCode: 'Claude Code', cursor: 'Cursor', gemini: 'Gemini CLI', clineRoo: 'Cline / Roo Code', continueAider: 'Continue / Aider', amazonCodex: 'Amazon Q / Codex CLI',
    thClient: 'Client', thMcp: 'Outbound MCP tools', thRouting: 'Targeted inbound routing', supported: 'Supported',
    notImplemented: 'Not implemented', manualMcp: 'Manual MCP configuration',
    commandsEyebrow: '05 / COMMANDS', commandsTitle: 'Direct controls.<br>No surprises.',
    cmdSession: 'Browse and select the active session.', cmdCurrent: 'Show the active session name and ID.',
    cmdModels: 'Browse providers and switch the session model.', cmdFiles: 'List received files for the active session.',
    cmdHelp: 'Restore the keyboard and list commands.', securityEyebrow: '06 / SECURITY MODEL',
    securityTitle: 'Keep control<br>on your machine.', securityLink: 'Read the security notes',
    security1: 'Owner chat is verified before message routing.', security2: 'Credentials live in private runtime config, not in the repository.',
    security3: 'Outbound files are constrained by allowlisted roots and a deny list.', security4: 'Session identifiers are validated before API calls.',
    security5: 'A local lock prevents duplicate Telegram listeners.', security6: 'Targeted routing is OpenCode-specific; MCP is not remote shell access.',
    installEyebrow: '07 / GET STARTED', installTitle: 'A clear path to your first message.',
    installText: 'Install from the source repository, then let the guided setup connect your bot and coding-agent CLI.',
    installPython: 'Python 3.11 or newer', installLinux: 'Linux + systemd user services',
    installMethod: 'Guided source install', installMethodText: 'The installer checks your environment, backs up CLI config before changing it, and keeps private bot settings in your user config directory.',
    installSourceCta: 'Open the source repository', installNoBinary: 'There is no standalone binary download. The installer copies the reviewed project files to your user directories.',
    installStepsHeading: 'Install in a few steps', installStepOneTitle: 'Clone the repository', installStepTwoTitle: 'Run the guided installer',
    installStepTwoText: 'Choose a detected CLI. Setup asks before changing its config, then prompts for your Telegram bot token.',
    installStepThreeTitle: 'Connect your Telegram chat', installStepThreeText: 'Open a private chat with your bot and send /start. Setup saves your owner chat ID and enables the listener service.',
    installStepFourTitle: 'Restart your CLI', installStepFourText: 'Restart the selected coding-agent CLI to load MCP, then send /start in Telegram. Check the service with telecode status.',
    copyCommand: 'Copy', copyAria: 'Copy command', copySuccess: 'Command copied.', copyFailure: 'Could not copy. Select the command to copy it.',
    copyCloneAria: 'Copy repository clone command', copyInstallAria: 'Copy installer command', copyStatusAria: 'Copy status command',
    installGuide: 'Detailed installation guide', installSecurity: 'Security notes', footerLine: 'Local sessions, reachable by design.',
    securityNav: 'Security', license: 'MIT license', previewSelected: '{provider} selected', previewAction: '{action} preview'
  },
  ar: {
    pageTitle: 'TeleCode — جلسات البرمجة في متناولك',
    metaDescription: 'يربط TeleCode تيليجرام بجلسات OpenCode المحلية وأدوات MCP لوكلاء البرمجة.',
    skip: 'انتقل إلى المحتوى', homeAria: 'الصفحة الرئيسية لـ TeleCode', repositoryLink: 'Aetherdz / TeleCode', repositoryAria: 'مستودع TeleCode على GitHub (يفتح في علامة تبويب جديدة)', navOpen: 'فتح التنقل', navClose: 'إغلاق التنقل', mainNav: 'التنقل الرئيسي',
    switchLanguageAria: 'التبديل إلى الإنجليزية', phonePreview: 'معاينة توضيحية لاختيار النموذج', switchTheme: 'تغيير مظهر الألوان',
    themeToDarkAria: 'التبديل إلى الوضع الليلي', themeToLightAria: 'التبديل إلى الوضع النهاري',
    providerAria: 'اختيار {provider} كمزوّد للنموذج', previewButtonAria: '{action} المعاينة',
    navFlow: 'كيف يعمل', navIntegrations: 'التكاملات', navCommands: 'الأوامر', navSecurity: 'الأمان', navInstall: 'التثبيت',
    switchLanguage: 'English', darkMode: 'الوضع الليلي', lightMode: 'الوضع النهاري',
    heroEyebrow: 'من تيليجرام إلى جلساتك المحلية', heroTitle: 'جلسة البرمجة،<br><em>أصبحت أقرب.</em>',
    heroLede: 'اختر جلسة OpenCode، وأرسل إليها من تيليجرام، واستقبل الردود عبر أدوات MCP المحلية.',
    getStarted: 'ابدأ الآن', viewSource: 'عرض المصدر', selectedTarget: 'الهدف المحدد: جلسة OpenCode',
    localListener: 'مستمع محلي', pythonVersion: 'Python 3.11+', stdlib: 'المكتبة القياسية', mitLicense: 'رخصة MIT', github: 'GitHub',
    mapTitle: 'مسار رسائل TeleCode', mapDesc: 'توجّه محادثة المالك في تيليجرام الرسائل عبر الجسر المحلي إلى جلسة OpenCode محددة، ثم تستقبل ردود الوكيل عبر أدوات MCP.',
    mapOwner: 'محادثة المالك', mapBridge: 'الجسر المحلي', mapCheck: 'تحقق المالك · توجيه', mapSession: 'الجلسة المحددة', mapRoute: 'المسار المحلي / 01', mapReply: 'رد MCP ↗',
    loopEyebrow: '01 / آلية العمل', loopTitle: 'مالك واحد.<br>ومسار واضح.',
    step1Title: 'اربط البوت', step1Text: 'أعدّ محادثة المالك وشغّل المستمع محليًا. لن يقبل إلا التحديثات المصرح بها.',
    step2Title: 'اختر جلسة', step2Text: 'اختر جلسة OpenCode باسمها. ستصل الرسائل الواردة إلى الهدف النشط.',
    step3Title: 'واصل عملك', step3Text: 'أرسل طلباتك عبر تيليجرام. يستطيع الوكيل الرد عبر MCP وإعادة الملفات المسموح بها.',
    capEyebrow: '02 / الإمكانات', capTitle: 'مصمم للعمل، وليس كطرفية تحكم عن بُعد.',
    cap1Title: 'توجيه الجلسات بالاسم', cap1Text: 'تصفح الجلسات حسب الاسم، وتنقل بين الصفحات، وحدد الهدف النشط بوضوح.',
    cap2Title: 'اختيار النموذج', cap2Text: 'تصفح المزوّدين والنماذج في تيليجرام، ثم حدّث نموذج جلسة OpenCode النشطة.',
    cap3Title: 'تبادل الملفات', cap3Text: 'وجّه المرفقات إلى الجلسة التي استقبلتها، واقصر الملفات الصادرة على المسارات المسموح بها.',
    cap4Title: 'ردود MCP', cap4Text: 'يمكن لعملاء وكلاء البرمجة المحليين استخدام أدوات الجسر لإرسال النصوص والملفات وحالة الجلسة.',
    cap5Title: 'التحقق من المالك', cap5Text: 'يُتحقق من المحادثة قبل التوجيه، ومن هوية المرسل عندما يوفرها تيليجرام.',
    cap6Title: 'تشغيل محلي', cap6Text: 'لا Webhook عام ولا وسيط مستضاف. ويمكن لخدمة systemd تشغيل المستمع تلقائيًا.',
    showEyebrow: '03 / واجهة تيليجرام', showTitle: 'واجهة تحكم صغيرة لإنجاز العمل.',
    showText: 'اختر جلسة، وتحقق من الهدف النشط، أو غيّر النموذج دون الانتقال إلى لوحة تحكم في المتصفح.',
    kbLabel: 'خيارات لوحة مفاتيح تيليجرام', kbSessions: 'الجلسات', kbCurrent: 'الجلسة الحالية', kbModels: 'النماذج', kbHelp: 'مساعدة',
    previewLabel: 'معاينة اختيار النموذج', providerTitle: 'اختر مزوّد نموذج', preview: 'معاينة', chooseProvider: 'اختر مزوّدًا',
    previous: 'السابق', next: 'التالي', providers: 'المزوّدون', close: 'إغلاق',
    intEyebrow: '04 / التكاملات', intTitle: 'حدود دعم واضحة.', tableCaption: 'دعم التكامل مع وكلاء البرمجة',
    intText: 'يدعم OpenCode توجيه رسائل تيليجرام إلى جلسة محددة. ويمكن للعملاء الآخرين استخدام أدوات MCP الصادرة حسب دعم إعداداتهم.',
    opencode: 'OpenCode', claudeCode: 'Claude Code', cursor: 'Cursor', gemini: 'Gemini CLI', clineRoo: 'Cline / Roo Code', continueAider: 'Continue / Aider', amazonCodex: 'Amazon Q / Codex CLI',
    thClient: 'العميل', thMcp: 'أدوات MCP الصادرة', thRouting: 'توجيه الرسائل الواردة', supported: 'مدعوم',
    notImplemented: 'غير مطبق', manualMcp: 'إعداد MCP يدويًا',
    commandsEyebrow: '05 / الأوامر', commandsTitle: 'تحكم مباشر.<br>بلا مفاجآت.',
    cmdSession: 'تصفح الجلسة النشطة واخترها.', cmdCurrent: 'اعرض اسم الجلسة النشطة ومعرّفها.',
    cmdModels: 'تصفح المزوّدين وغيّر نموذج الجلسة.', cmdFiles: 'اعرض الملفات المستلمة للجلسة النشطة.',
    cmdHelp: 'أظهر لوحة المفاتيح وقائمة الأوامر.', securityEyebrow: '06 / نموذج الأمان',
    securityTitle: 'تحكمك يبقى<br>على جهازك.', securityLink: 'اقرأ ملاحظات الأمان',
    security1: 'يتم التحقق من محادثة المالك قبل توجيه الرسائل.', security2: 'تُحفظ بيانات الاعتماد في إعدادات تشغيل خاصة، لا في المستودع.',
    security3: 'تُقيد الملفات الصادرة بمسارات مسموح بها وقائمة حظر.', security4: 'تُتحقق معرّفات الجلسات قبل استدعاء API.',
    security5: 'يمنع قفل محلي تشغيل مستمعي تيليجرام مكررين.', security6: 'التوجيه المحدد خاص بـ OpenCode؛ وMCP ليس وصولًا إلى طرفية عن بُعد.',
    installEyebrow: '07 / ابدأ الآن', installTitle: 'خطوات واضحة لأول رسالة.',
    installText: 'ثبّت من مستودع المصدر، ثم اتبع الإعداد الموجّه لربط البوت وعميل وكيل البرمجة.',
    installPython: 'Python 3.11 أو أحدث', installLinux: 'Linux مع خدمات systemd للمستخدم',
    installMethod: 'تثبيت موجّه من المصدر', installMethodText: 'يفحص المثبّت بيئتك، وينشئ نسخة احتياطية قبل تعديل إعدادات العميل، ويحفظ بيانات البوت الخاصة ضمن إعدادات المستخدم.',
    installSourceCta: 'افتح مستودع المصدر', installNoBinary: 'لا يتوفر ملف تنفيذي مستقل للتنزيل. ينسخ المثبّت ملفات المشروع التي راجعتها إلى مجلدات المستخدم.',
    installStepsHeading: 'التثبيت في خطوات قليلة', installStepOneTitle: 'استنسخ المستودع', installStepTwoTitle: 'شغّل المثبّت الموجّه',
    installStepTwoText: 'اختر عميلًا مكتشفًا. يطلب الإعداد موافقتك قبل تغيير ملف الإعداد، ثم يطلب رمز بوت تيليجرام.',
    installStepThreeTitle: 'اربط محادثة تيليجرام', installStepThreeText: 'افتح محادثة خاصة مع البوت وأرسل /start. يحفظ الإعداد معرّف محادثة المالك ويفعّل خدمة المستمع.',
    installStepFourTitle: 'أعد تشغيل العميل', installStepFourText: 'أعد تشغيل عميل وكيل البرمجة المحدد لتحميل MCP، ثم أرسل /start في تيليجرام. تحقق من الخدمة بالأمر telecode status.',
    copyCommand: 'نسخ', copyAria: 'نسخ الأمر', copySuccess: 'تم نسخ الأمر.', copyFailure: 'تعذر النسخ. حدد الأمر وانسخه يدويًا.',
    copyCloneAria: 'نسخ أمر استنساخ المستودع', copyInstallAria: 'نسخ أمر تشغيل المثبّت', copyStatusAria: 'نسخ أمر التحقق من الحالة',
    installGuide: 'دليل التثبيت المفصل', installSecurity: 'ملاحظات الأمان', footerLine: 'جلسات محلية، في متناولك.',
    securityNav: 'الأمان', license: 'رخصة MIT', previewSelected: 'تم اختيار {provider}', previewAction: 'معاينة {action}'
  }
};

let language = 'en';
try { language = localStorage.getItem('telecode-language') === 'ar' ? 'ar' : 'en'; } catch (_) {}
function applyLanguage(next) {
  language = next === 'ar' ? 'ar' : 'en';
  const dict = messages[language];
  root.lang = language;
  root.dir = language === 'ar' ? 'rtl' : 'ltr';
  document.title = dict.pageTitle;
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const value = dict[el.dataset.i18n];
    if (value !== undefined) el.textContent = value;
  });
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    const value = dict[el.dataset.i18nHtml];
    if (value !== undefined) {
      const template = document.createElement('template');
      template.innerHTML = value;
      el.replaceChildren(template.content.cloneNode(true));
    }
  });
  document.querySelectorAll('[data-i18n-aria]').forEach(el => {
    const value = dict[el.dataset.i18nAria];
    if (value !== undefined) el.setAttribute('aria-label', value);
  });
  document.querySelectorAll('[data-preview-key]').forEach(el => {
    const value = dict[el.dataset.previewKey];
    if (value !== undefined) el.textContent = value;
  });
  document.querySelectorAll('[data-i18n-svg]').forEach(el => {
    const value = dict[el.dataset.i18nSvg];
    if (value !== undefined) el.textContent = value;
  });
  const copyStatus = document.querySelector('#copy-status');
  if (copyStatus) copyStatus.textContent = '';
  const description = document.querySelector('[data-i18n-content="metaDescription"]');
  if (description) description.content = dict.metaDescription;
  if (languageButton) languageButton.setAttribute('lang', language === 'ar' ? 'en' : 'ar');
  document.querySelectorAll('.provider').forEach(button => button.setAttribute('aria-label', dict.providerAria.replace('{provider}', button.dataset.provider)));
  document.querySelectorAll('[data-preview-key]').forEach(button => button.setAttribute('aria-label', dict.previewButtonAria.replace('{action}', dict[button.dataset.previewKey])));
  document.querySelectorAll('[data-copy-aria]').forEach(button => button.setAttribute('aria-label', dict[button.dataset.copyAria] || dict.copyAria));
  updatePreview();
  const themeColor = document.querySelector('#theme-color-meta');
  if (themeColor) themeColor.content = root.dataset.theme === 'dark' ? '#171817' : '#F6F3EA';
  if (languageButton) languageButton.textContent = dict.switchLanguage;
  if (nav?.classList.contains('open') && window.matchMedia('(max-width: 900px)').matches) closeNavigation();
  try { localStorage.setItem('telecode-language', language); } catch (_) {}
  updateThemeButton();
  updateNavigationLabel();
}
function updateThemeButton() {
  if (!themeButton) return;
  const dark = root.dataset.theme === 'dark';
  themeButton.textContent = messages[language][dark ? 'lightMode' : 'darkMode'];
  themeButton.setAttribute('aria-label', messages[language][dark ? 'themeToLightAria' : 'themeToDarkAria']);
}
function updateNavigationLabel() {
  if (!navToggle) return;
  navToggle.setAttribute('aria-label', messages[language][navToggle.getAttribute('aria-expanded') === 'true' ? 'navClose' : 'navOpen']);
}
function setTheme(theme) {
  root.dataset.theme = theme === 'dark' ? 'dark' : 'light';
  try { localStorage.setItem('telecode-theme', root.dataset.theme); } catch (_) {}
  const themeColor = document.querySelector('#theme-color-meta');
  if (themeColor) themeColor.content = root.dataset.theme === 'dark' ? '#171817' : '#F6F3EA';
  updateThemeButton();
}
applyLanguage(language);
setTheme(root.dataset.theme || 'light');
languageButton?.addEventListener('click', () => {
  applyLanguage(language === 'ar' ? 'en' : 'ar');
  if (nav?.classList.contains('open') && window.matchMedia('(max-width: 900px)').matches) closeNavigation();
});
themeButton?.addEventListener('click', () => setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'));

function closeNavigation() {
  nav?.classList.remove('open');
  if (window.matchMedia('(max-width: 900px)').matches) nav?.setAttribute('inert', '');
  else nav?.removeAttribute('inert');
  navToggle?.setAttribute('aria-expanded', 'false');
  updateNavigationLabel();
}
if (window.matchMedia('(max-width: 900px)').matches) closeNavigation();
else nav?.removeAttribute('inert');
navToggle?.addEventListener('click', () => {
  const open = navToggle.getAttribute('aria-expanded') !== 'true';
  navToggle.setAttribute('aria-expanded', String(open));
  updateNavigationLabel();
  nav?.classList.toggle('open', open);
  if (open) nav?.removeAttribute('inert');
  else nav?.setAttribute('inert', '');
});
nav?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
  if (!window.matchMedia('(max-width: 900px)').matches) return;
  const destination = link.getAttribute('href');
  closeNavigation();
  if (destination?.startsWith('#')) {
    const target = document.querySelector(destination);
    const heading = target?.matches('h1,h2,h3') ? target : target?.querySelector('h1,h2,h3');
    if (heading) {
      if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
      requestAnimationFrame(() => heading.focus({ preventScroll: true }));
    }
  }
}));
document.querySelectorAll('a[href^="#"]').forEach(link => {
  if (nav?.contains(link)) return;
  link.addEventListener('click', () => {
    if (nav?.classList.contains('open') && window.matchMedia('(max-width: 900px)').matches) closeNavigation();
  });
});
document.querySelector('.skip')?.addEventListener('click', () => {
  if (nav?.classList.contains('open') && window.matchMedia('(max-width: 900px)').matches) closeNavigation();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && nav?.classList.contains('open')) {
    closeNavigation();
    navToggle?.focus();
  }
});
const desktopQuery = window.matchMedia('(min-width: 901px)');
const syncNavigationBreakpoint = event => {
  if (event.matches) {
    nav?.classList.remove('open');
    nav?.removeAttribute('inert');
    navToggle?.setAttribute('aria-expanded', 'false');
    updateNavigationLabel();
  } else closeNavigation();
};
if (desktopQuery.addEventListener) desktopQuery.addEventListener('change', syncNavigationBreakpoint);
else desktopQuery.addListener?.(syncNavigationBreakpoint);
document.addEventListener('pointerdown', event => {
  if (!nav?.classList.contains('open') || !window.matchMedia('(max-width: 900px)').matches) return;
  if (nav.contains(event.target) || navToggle?.contains(event.target)) return;
  closeNavigation();
});

function updatePreview() {
  if (!preview || !previewState.value) return;
  const dict = messages[language];
  preview.textContent = previewState.type === 'provider'
    ? dict.previewSelected.replace('{provider}', previewState.value)
    : dict.previewAction.replace('{action}', dict[previewState.value]);
}
document.querySelectorAll('.provider').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('.provider').forEach(item => {
    const selected = item === button;
    item.classList.toggle('selected', selected);
    item.setAttribute('aria-pressed', String(selected));
  });
  previewState = { type: 'provider', value: button.dataset.provider };
  updatePreview();
}));
document.querySelectorAll('.phone-controls button').forEach(button => button.addEventListener('click', () => {
  previewState = { type: 'action', value: button.dataset.previewKey };
  updatePreview();
}));

document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    const dict = messages[language];
    const status = document.querySelector('#copy-status');
    const previousFocus = document.activeElement;
    const label = dict[button.dataset.copyAria] || dict.copyAria;
    button.setAttribute('aria-label', label);
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(button.dataset.copy);
    } else {
      const field = document.createElement('textarea');
      field.value = button.dataset.copy;
      field.setAttribute('readonly', '');
      field.style.position = 'fixed';
      field.style.opacity = '0';
      document.body.append(field);
      field.select();
      let copied = false;
      try { copied = document.execCommand('copy'); }
      finally { field.remove(); previousFocus?.focus?.(); }
      if (!copied) throw new Error('Copy unavailable');
    }
    if (status) status.textContent = dict.copySuccess;
    window.setTimeout(() => {
      if (status) status.textContent = '';
    }, 2400);
  } catch (_) {
    if (status) status.textContent = dict.copyFailure;
    window.setTimeout(() => {
      if (status) status.textContent = '';
    }, 4000);
  }
}));

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
if ('IntersectionObserver' in window && !reduceMotion) {
  const observer = new IntersectionObserver(entries => entries.forEach(entry => {
    if (entry.isIntersecting) { entry.target.classList.add('visible'); observer.unobserve(entry.target); }
  }), { threshold: .12 });
  document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
} else document.querySelectorAll('.reveal').forEach(el => el.classList.add('visible'));
