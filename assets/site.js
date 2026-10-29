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
    switchLanguageAria: 'Change language', phonePreview: 'Illustrative model picker preview', switchTheme: 'Switch color theme', mapScrollAria: 'Scrollable routing diagram. Use left and right arrow keys to explore.',
    nextLanguageCode: 'ar', nextLanguageName: 'العربية',
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
    installSourceCta: 'Open the source repository', installNoBinary: 'Review the installer before running it. The command downloads the source, then launches the guided setup.',
    copyInstallCommandAria: 'Copy the guided install command', installCommandTitle: 'One command to begin', installCommandNote: 'Review install.sh in the public repository first. The command downloads that script and starts guided setup. Linux + systemd user services; Python 3.11+.',
    installStepsHeading: 'Install in a few steps', installStepOneTitle: 'Clone the repository', installStepTwoTitle: 'Run the guided installer',
    installStepTwoText: 'Choose a detected CLI with the arrow keys and Enter. Setup asks before changing its config, then requests your Telegram bot token.',
    installStepThreeTitle: 'Connect your Telegram chat', installStepThreeText: 'Enter your numeric ID from @Getmyid_bot, or choose automatic detection and send /start to your own bot.',
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
    switchLanguageAria: 'تغيير اللغة', phonePreview: 'معاينة توضيحية لاختيار النموذج', switchTheme: 'تغيير مظهر الألوان', mapScrollAria: 'مخطط مسار قابل للتمرير. استخدم السهمين الأيمن والأيسر لاستعراضه.',
    nextLanguageCode: 'es', nextLanguageName: 'Español',
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
    installSourceCta: 'افتح مستودع المصدر', installNoBinary: 'راجع المثبّت قبل تشغيله. ينزّل الأمر المصدر ثم يبدأ الإعداد الموجّه.',
    copyInstallCommandAria: 'نسخ أمر التثبيت الموجّه', installCommandTitle: 'ابدأ بأمر واحد', installCommandNote: 'راجع install.sh في المستودع العام أولًا. ينزّل الأمر السكربت ويبدأ الإعداد الموجّه. يتطلب Linux مع systemd وPython 3.11+.',
    installStepsHeading: 'التثبيت في خطوات قليلة', installStepOneTitle: 'استنسخ المستودع', installStepTwoTitle: 'شغّل المثبّت الموجّه',
    installStepTwoText: 'اختر العميل بالأسهم واضغط Enter. يطلب الإعداد موافقتك قبل تعديل ملفه، ثم يطلب رمز البوت.',
    installStepThreeTitle: 'اربط محادثة تيليجرام', installStepThreeText: 'أدخل معرّفك الرقمي من @Getmyid_bot، أو اختر الكشف التلقائي وأرسل /start إلى بوتك.',
    installStepFourTitle: 'أعد تشغيل العميل', installStepFourText: 'أعد تشغيل عميل وكيل البرمجة المحدد لتحميل MCP، ثم أرسل /start في تيليجرام. تحقق من الخدمة بالأمر telecode status.',
    copyCommand: 'نسخ', copyAria: 'نسخ الأمر', copySuccess: 'تم نسخ الأمر.', copyFailure: 'تعذر النسخ. حدد الأمر وانسخه يدويًا.',
    copyCloneAria: 'نسخ أمر استنساخ المستودع', copyInstallAria: 'نسخ أمر تشغيل المثبّت', copyStatusAria: 'نسخ أمر التحقق من الحالة',
    installGuide: 'دليل التثبيت المفصل', installSecurity: 'ملاحظات الأمان', footerLine: 'جلسات محلية، في متناولك.',
    securityNav: 'الأمان', license: 'رخصة MIT', previewSelected: 'تم اختيار {provider}', previewAction: 'معاينة {action}'
  },
  es: {
    pageTitle: 'TeleCode — tus sesiones de programación, al alcance',
    metaDescription: 'TeleCode conecta Telegram con sesiones locales de OpenCode y herramientas MCP para agentes de programación.',
    skip: 'Saltar al contenido', homeAria: 'Inicio de TeleCode', repositoryLink: 'Aetherdz / TeleCode', repositoryAria: 'Repositorio de TeleCode en GitHub (se abre en una pestaña nueva)', navOpen: 'Abrir navegación', navClose: 'Cerrar navegación', mainNav: 'Navegación principal',
    switchLanguageAria: 'Cambiar idioma', phonePreview: 'Vista ilustrativa del selector de modelos', switchTheme: 'Cambiar tema de color', mapScrollAria: 'Diagrama desplazable. Usa las flechas izquierda y derecha para explorarlo.', nextLanguageCode: 'en', nextLanguageName: 'English',
    themeToDarkAria: 'Cambiar al modo oscuro', themeToLightAria: 'Cambiar al modo claro', providerAria: 'Elegir {provider} como proveedor del modelo', previewButtonAria: 'Vista previa de {action}',
    navFlow: 'Cómo funciona', navIntegrations: 'Integraciones', navCommands: 'Comandos', navSecurity: 'Seguridad', navInstall: 'Instalar', switchLanguage: 'English', darkMode: 'Modo oscuro', lightMode: 'Modo claro',
    heroEyebrow: 'DE TELEGRAM A SESIONES LOCALES', heroTitle: 'Tu sesión de programación,<br><em>más cerca.</em>', heroLede: 'Elige una sesión de OpenCode, envíale mensajes desde Telegram y recibe respuestas mediante herramientas MCP locales.', getStarted: 'Comenzar', viewSource: 'Ver código', selectedTarget: 'Destino seleccionado: sesión de OpenCode', localListener: 'Servicio local', pythonVersion: 'Python 3.11+', stdlib: 'Biblioteca estándar', mitLicense: 'Licencia MIT', github: 'GitHub', mapTitle: 'Enrutamiento de mensajes de TeleCode', mapDesc: 'El chat del propietario en Telegram enruta mensajes mediante el puente local a una sesión de OpenCode y recibe respuestas a través de herramientas MCP.', mapOwner: 'CHAT DEL PROPIETARIO', mapBridge: 'PUENTE LOCAL', mapCheck: 'VERIFICACIÓN · RUTA', mapSession: 'SESIÓN ELEGIDA', mapRoute: 'RUTA LOCAL / 01', mapReply: 'RESPUESTA MCP ↗',
    loopEyebrow: '01 / EL FLUJO', loopTitle: 'Un propietario.<br>Una ruta clara.', step1Title: 'Conecta tu bot', step1Text: 'Configura el chat del propietario y ejecuta el servicio localmente. Solo acepta actualizaciones autorizadas.', step2Title: 'Elige una sesión', step2Text: 'Selecciona una sesión de OpenCode por nombre. Los mensajes entrantes se dirigen al destino activo.', step3Title: 'Sigue trabajando', step3Text: 'Envía solicitudes por Telegram. El agente puede responder mediante MCP y devolver archivos permitidos.', capEyebrow: '02 / FUNCIONES', capTitle: 'Diseñado para trabajar, no para ofrecer una terminal remota.', cap1Title: 'Enrutamiento por sesión', cap1Text: 'Explora sesiones por nombre, navega páginas y elige explícitamente el destino activo.', cap2Title: 'Selección de modelo', cap2Text: 'Explora proveedores y modelos en Telegram y actualiza la sesión activa de OpenCode.', cap3Title: 'Intercambio de archivos', cap3Text: 'Dirige adjuntos a la sesión que los recibió y limita los archivos salientes a rutas permitidas.', cap4Title: 'Respuestas MCP', cap4Text: 'Los clientes locales pueden usar herramientas del puente para enviar texto, archivos y estado.', cap5Title: 'Verificación del propietario', cap5Text: 'Se comprueba el chat antes del enrutamiento y el remitente cuando Telegram lo proporciona.', cap6Title: 'Ejecución local', cap6Text: 'Sin webhook público ni intermediario alojado. Un servicio systemd opcional inicia el listener.',
    showEyebrow: '03 / INTERFAZ DE TELEGRAM', showTitle: 'Un pequeño panel para el trabajo real.', showText: 'Elige una sesión, consulta el destino activo o cambia su modelo sin abrir un panel web.', kbLabel: 'Opciones del teclado de Telegram', kbSessions: 'Sesiones', kbCurrent: 'Sesión actual', kbModels: 'Modelos', kbHelp: 'Ayuda', previewLabel: 'VISTA DEL SELECTOR DE MODELOS', providerTitle: 'ELIGE UN PROVEEDOR', preview: 'VISTA PREVIA', chooseProvider: 'Elige un proveedor', previous: 'Anterior', next: 'Siguiente', providers: 'Proveedores', close: 'Cerrar',
    intEyebrow: '04 / INTEGRACIONES', intTitle: 'Límites de compatibilidad claros.', tableCaption: 'Compatibilidad con clientes de programación', intText: 'OpenCode admite el enrutamiento a sesiones concretas. Otros clientes pueden usar herramientas MCP salientes si admiten esa configuración.', opencode: 'OpenCode', claudeCode: 'Claude Code', cursor: 'Cursor', gemini: 'Gemini CLI', clineRoo: 'Cline / Roo Code', continueAider: 'Continue / Aider', amazonCodex: 'Amazon Q / Codex CLI', thClient: 'Cliente', thMcp: 'Herramientas MCP salientes', thRouting: 'Enrutamiento entrante', supported: 'Compatible', notImplemented: 'No implementado', manualMcp: 'Configuración MCP manual',
    commandsEyebrow: '05 / COMANDOS', commandsTitle: 'Controles directos.<br>Sin sorpresas.', cmdSession: 'Explora y selecciona la sesión activa.', cmdCurrent: 'Muestra el nombre y el ID de la sesión activa.', cmdModels: 'Explora proveedores y cambia el modelo.', cmdFiles: 'Lista los archivos recibidos para la sesión activa.', cmdHelp: 'Restaura el teclado y muestra los comandos.', securityEyebrow: '06 / SEGURIDAD', securityTitle: 'Mantén el control<br>en tu equipo.', securityLink: 'Leer notas de seguridad', security1: 'Se verifica el chat del propietario antes de enrutar mensajes.', security2: 'Las credenciales se guardan en configuración privada, no en el repositorio.', security3: 'Los archivos salientes se limitan a rutas permitidas y una lista de exclusión.', security4: 'Los identificadores de sesión se validan antes de las llamadas API.', security5: 'Un bloqueo local evita listeners de Telegram duplicados.', security6: 'El enrutamiento específico es para OpenCode; MCP no es acceso a un shell remoto.',
    installEyebrow: '07 / EMPEZAR', installTitle: 'Un camino claro hasta tu primer mensaje.', installText: 'Instala desde el código fuente y deja que el asistente conecte tu bot y cliente de programación.', installPython: 'Python 3.11 o posterior', installLinux: 'Linux + servicios systemd de usuario', installMethod: 'Instalación guiada desde el código', installMethodText: 'El instalador comprueba el entorno, guarda una copia de la configuración antes de cambiarla y mantiene las credenciales privadas en tu directorio de usuario.', installSourceCta: 'Abrir el repositorio', installNoBinary: 'Revisa el instalador antes de ejecutarlo. El comando descarga el código y comienza la configuración guiada.', copyInstallCommandAria: 'Copiar comando de instalación guiada', installCommandTitle: 'Empieza con un comando', installCommandNote: 'Revisa primero install.sh en el repositorio público. El comando descarga el script e inicia la configuración guiada. Requiere Linux, systemd y Python 3.11+.', installStepsHeading: 'Instala en unos pasos', installStepOneTitle: 'Clona el repositorio', installStepTwoTitle: 'Ejecuta el instalador guiado', installStepTwoText: 'Elige un cliente detectado con las flechas y Enter. Se pedirá permiso antes de cambiar su configuración y luego el token del bot.', installStepThreeTitle: 'Conecta tu chat de Telegram', installStepThreeText: 'Introduce tu ID numérico de @Getmyid_bot o elige la detección automática y envía /start a tu bot.', installStepFourTitle: 'Reinicia el cliente', installStepFourText: 'Reinicia el cliente para cargar MCP, envía /start en Telegram y comprueba el servicio con telecode status.', copyCommand: 'Copiar', copyAria: 'Copiar comando', copySuccess: 'Comando copiado.', copyFailure: 'No se pudo copiar. Selecciona el comando y cópialo manualmente.', copyCloneAria: 'Copiar comando para clonar el repositorio', copyInstallAria: 'Copiar comando del instalador', copyStatusAria: 'Copiar comando de estado', installGuide: 'Guía detallada de instalación', installSecurity: 'Notas de seguridad', footerLine: 'Sesiones locales, accesibles por diseño.', securityNav: 'Seguridad', license: 'Licencia MIT', previewSelected: '{provider} seleccionado', previewAction: 'Vista previa de {action}'
  }
};

const supportedLanguages = ['en', 'ar', 'es'];
let language = 'en';
try {
  const savedLanguage = localStorage.getItem('telecode-language');
  language = supportedLanguages.includes(savedLanguage) ? savedLanguage : 'en';
} catch (_) {}
function applyLanguage(next) {
  language = supportedLanguages.includes(next) ? next : 'en';
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
  const mapStage = document.querySelector('.map-stage');
  if (mapStage) mapStage.setAttribute('aria-label', dict.mapScrollAria);
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
  if (languageButton) languageButton.setAttribute('lang', messages[language].nextLanguageCode);
  document.querySelectorAll('.provider').forEach(button => button.setAttribute('aria-label', dict.providerAria.replace('{provider}', button.dataset.provider)));
  document.querySelectorAll('[data-preview-key]').forEach(button => button.setAttribute('aria-label', dict.previewButtonAria.replace('{action}', dict[button.dataset.previewKey])));
  document.querySelectorAll('[data-copy-aria]').forEach(button => button.setAttribute('aria-label', dict[button.dataset.copyAria] || dict.copyAria));
  updatePreview();
  const themeColor = document.querySelector('#theme-color-meta');
  if (themeColor) themeColor.content = root.dataset.theme === 'dark' ? '#171817' : '#F6F3EA';
  if (languageButton) languageButton.textContent = dict.nextLanguageName;
  if (nav?.classList.contains('open') && window.matchMedia('(max-width: 1000px)').matches) closeNavigation();
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
  const current = supportedLanguages.indexOf(language);
  applyLanguage(supportedLanguages[(current + 1) % supportedLanguages.length]);
  if (nav?.classList.contains('open') && window.matchMedia('(max-width: 1000px)').matches) closeNavigation();
});
themeButton?.addEventListener('click', () => setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'));

function closeNavigation() {
  nav?.classList.remove('open');
  if (window.matchMedia('(max-width: 1000px)').matches) nav?.setAttribute('inert', '');
  else nav?.removeAttribute('inert');
  navToggle?.setAttribute('aria-expanded', 'false');
  updateNavigationLabel();
}
if (window.matchMedia('(max-width: 1000px)').matches) closeNavigation();
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
  if (!window.matchMedia('(max-width: 1000px)').matches) return;
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
    if (nav?.classList.contains('open') && window.matchMedia('(max-width: 1000px)').matches) closeNavigation();
  });
});
document.querySelector('.skip')?.addEventListener('click', () => {
  if (nav?.classList.contains('open') && window.matchMedia('(max-width: 1000px)').matches) closeNavigation();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && nav?.classList.contains('open')) {
    closeNavigation();
    navToggle?.focus();
  }
});
const desktopQuery = window.matchMedia('(min-width: 1000.01px)');
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
  if (!nav?.classList.contains('open') || !window.matchMedia('(max-width: 1000px)').matches) return;
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
