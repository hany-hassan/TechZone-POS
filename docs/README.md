<div dir="rtl" style="text-align: right; direction: rtl;">

# 📁 فهرس وثائق مشروع تك زون (TechZone Docs)

هذا المجلد يحتوي على الوثائق التأسيسية والهندسية والمرجعية لنظام **تك زون للإلكترونيات (TechZone POS & Shop OS)** وفق أفضل الممارسات الهندسية.

---

## 1. وثائق المشروع الرئيسية (Project Foundation Docs)

| الملف | بيجاوب على إيه | اللغة |
|---|---|---|
| [`PRD.md`](PRD.md) | **وثيقة متطلبات المنتج**: ما هو النظام، أهدافه القابلة للقياس، المستخدمين، النطاق المشمول والمؤجل، ومواصفات كل شاشة. | عربي |
| [`ROADMAP.md`](ROADMAP.md) | **خارطة طريق التطوير**: المراحل المتبقية، المهام المحددة، وبوابات الاختبار الإلزامية لكل مرحلة. | عربي |
| [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md) | **خطة التنفيذ التفصيلية للمقترحات**: خطوات تنفيذ 8 مهام أمنية وتشغيلية ومعمارية مع الأولويات. | عربي |
| [`OWNER-CONTROL-PLAN.md`](OWNER-CONTROL-PLAN.md) | **خطة وضع المالك وإدارة الهيكلة والقوالب**: التحكم بالأقسام، المصادقة المستقلة، قوالب النشاط التجاري، وبناء قاعدة جديدة نظيفة. | English |
| [`OPEN-QUESTIONS.md`](OPEN-QUESTIONS.md) | **الأسئلة والقرارات المفتوحة**: النقاط التي تحتاج قراراً، التوصية المقترحة، والمرحلة المستهدفة. | عربي |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | **البنية الهندسية والمعمارية**: مخطط النظام، تدفق البيانات، الجسر، حارس الأقسام الخادمي، وهيكل المجلدات. | English |
| [`DATA-MODEL.md`](DATA-MODEL.md) | **مخطط قاعدة البيانات**: تفاصيل الجداول الـ 31، الحقول والأنواع، والعلاقات، ومصفوفة الصلاحيات الـ 49 (10 مجموعات). | English |
| [`STACK.md`](STACK.md) | **حزمة التقنيات المثبتة**: الإصدارات المحددة، أسباب الاختيار، وسياسات الترقية المتوافقة. | English |
| [`CODING-STANDARDS.md`](CODING-STANDARDS.md) | **معايير وجودة الكود**: قواعد Python، Vanilla JS، Tailwind، التعامل مع المبالغ، وقواعد الأمان وRTL. | English |
| [`TESTING.md`](TESTING.md) | **استراتيجية الاختبار**: فحوصات `selfcheck.py` الآلية (`234` فحصاً)، واختبارات الجودة والانحدار. | English |
| [`SECURITY.md`](SECURITY.md) | **سياسات الأمان والخصوصية**: نموذج التهديدات، التشفير بـ PBKDF2، وضع المالك، الصلاحيات، وحماية بيانات العملاء وفق القانون المصري. | English |
| [`DESIGN-SYSTEM.md`](DESIGN-SYSTEM.md) | **نظام التصميم وتجربة المستخدم**: مظهر TechZone OS، الألوان، الخطوط المحلية، قواعد الطباعة وقوالب الفواتير. | English |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | **دليل البناء والنشر**: تجميع ملف `TechZone.exe` عبر PyInstaller، التشغيل بدون تثبيت، والنسخ الاحتياطي. | English |

---

## 2. سجل القرارات الهندسية (Architecture Decision Records — ADRs)

| القرار | الموضوع | الحالة |
|---|---|---|
| [`adr/0000-template.md`](adr/0000-template.md) | القالب القياسي لتوثيق القرارات المعمارية الجديدة | Template |
| [`adr/0001-offline-sqlite-architecture.md`](adr/0001-offline-sqlite-architecture.md) | اختيار البنية المكتبية Offline باستخدام Python و pywebview و SQLite | Accepted |
| [`adr/0002-arabic-rtl-tailwind.md`](adr/0002-arabic-rtl-tailwind.md) | اعتماد واجهة Vanilla JS و Tailwind CSS مجمّع مع خطوط عربية محلية بالكامل | Accepted |
| [`adr/0003-owner-mode-and-module-registry.md`](adr/0003-owner-mode-and-module-registry.md) | فصل وضع المالك (Owner Mode) وسجل الأقسام عن صلاحيات مدير المحل | Accepted |

---

## 3. ملفات التوجيه والتهيئة في جذر المشروع

| الملف | الوصف |
|---|---|
| [`../AGENTS.md`](../AGENTS.md) | مصدر الحقيقة الموحد لأي وكيل ذكاء اصطناعي أو مطور يتعامل مع المشروع |
| [`../CLAUDE.md`](../CLAUDE.md) | دليل بدء الجلسات وقواعد التفاعل مع المطور لأدوات الذكاء الاصطناعي |
| [`../README.md`](../README.md) | الدليل الشامل المصور للمستخدم مع شرح كل شاشة وطريقة التشغيل |
| [`../CHANGELOG_ARCHIVE.md`](../CHANGELOG_ARCHIVE.md) | أرشيف سجل التغييرات التاريخية للمشروع لتخفيف حجم AGENTS.md |
| [`../.editorconfig`](../.editorconfig) | إعدادات المحرر الموحدة لمسافات الأسطر والترميز |

</div>
