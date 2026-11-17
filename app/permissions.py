"""السجل المركزي الموحد للصلاحيات التفصيلية (49 صلاحية في 10 مجموعات) وقوالب الوظائف الجاهزة."""
import json

PERMISSION_GROUPS = [
    {
        "key": "pos",
        "title": "نقاط البيع والكاشير والوردية",
        "icon": "point_of_sale",
        "color": "#2563eb",
        "perms": [
            {
                "key": "pos_sell",
                "label": "البيع وإصدار فواتير الكاشير (نقدي ومحفظة)",
                "desc": "يسمح: بفتح شاشة الكاشير، البحث بالباركود والاسم، وإتمام البيع النقدي/المحفظة. يمنع عند الإغلاق: أي عملية بيع من نقاط البيع.",
                "risk": "normal",
                "requires": [],
            },
            {
                "key": "shift_manage",
                "label": "فتح وإغلاق الوردية الخاصة بالموظف",
                "desc": "يسمح: بفتح وردية جديدة عند بدء العمل وإغلاقها عند تسليم الدرج. يمنع عند الإغلاق: فتح أو إغلاق الورديات.",
                "risk": "normal",
                "requires": [],
            },
            {
                "key": "shift_summary_view",
                "label": "كشف الجرد المتوقع قبل إغلاق الوردية (تعطيلها يفعّل الجرد الأعمى)",
                "desc": "يسمح: برؤية المبلغ المتوقع وتفاصيل المبيعات عند إغلاق الوردية وعداد مبيعاته. عند التعطيل: يعمل الكاشير بنظام «الجرد الأعمى» ويدخل ما عدّه فقط.",
                "risk": "financial",
                "requires": ["shift_manage"],
            },
            {
                "key": "pos_item_discount",
                "label": "خصم على صنف محدد داخل السلة (% أو مبلغ)",
                "desc": "يسمح: بتطبيق خصم على منتج واحد داخل السلة. يمنع عند الإغلاق: تغيير سعر الصنف بالخصم الفردي.",
                "risk": "financial",
                "requires": ["pos_sell"],
            },
            {
                "key": "pos_invoice_discount",
                "label": "خصم على إجمالي الفاتورة بالكامل",
                "desc": "يسمح: بإدخال خصم عام على مجموع الفاتورة. يمنع عند الإغلاق: تمرير أي خصم إجمالي على الفاتورة (حتى من الخادم).",
                "risk": "financial",
                "requires": ["pos_sell"],
            },
            {
                "key": "pos_price",
                "label": "تعديل سعر بيع الوحدة بحرية داخل السلة",
                "desc": "يسمح: برفع أو خفض سعر الوحدة يدوياً في الكاشير. يمنع عند الإغلاق: تغيير السعر المعتمد في الكتالوج.",
                "risk": "financial",
                "requires": ["pos_sell"],
            },
            {
                "key": "pos_credit_sale",
                "label": "البيع الآجل (تسجيل مديونية جديدة على العميل)",
                "desc": "يسمح: بتحويل جزء أو كل الفاتورة إلى آجل على حساب العميل. يمنع عند الإغلاق: أي بيع آجل نهائياً.",
                "risk": "critical",
                "requires": ["pos_sell"],
            },
            {
                "key": "pos_whatsapp",
                "label": "إرسال الفاتورة PDF عبر واتساب",
                "desc": "يسمح: بإرسال الفاتورة PDF من الكاشير أو الإيصال إلى واتساب العميل. يمنع عند الإغلاق: إرسال رسائل الفواتير.",
                "risk": "normal",
                "requires": [],
            },
            {
                "key": "pos_categories_manage",
                "label": "تخصيص وترتيب فئات شاشة الكاشير للجميع",
                "desc": "يسمح: بتغيير ترتيب أو إخفاء/إظهار الفئات العامة في الكاشير. يمنع عند الإغلاق: تعديل إعدادات الفئات.",
                "risk": "normal",
                "requires": ["pos_sell"],
            },
        ],
    },
    {
        "key": "history",
        "title": "سجل المبيعات والمرتجعات والإيصالات",
        "icon": "receipt_long",
        "color": "#ea580c",
        "perms": [
            {
                "key": "receipt_view",
                "label": "معاينة وطباعة الإيصال للفواتير المخول برؤيتها",
                "desc": "يسمح: بفتح شاشة معاينة الإيصال وطباعته لفواتيره فقط (أو للجميع مع صلاحية رؤية كل الفواتير).",
                "risk": "normal",
                "requires": [],
            },
            {
                "key": "history_view_own",
                "label": "دخول سجل المبيعات (فواتير هذا الموظف فقط)",
                "desc": "يسمح: بعرض والبحث في الفواتير التي أصدرها هذا الموظف نفسه فقط. يمنع عند الإغلاق: فتح سجل المبيعات أو فواتير غيره.",
                "risk": "normal",
                "requires": [],
            },
            {
                "key": "history_view_all",
                "label": "رؤية فواتير ومبيعات جميع الموظفين في المتجر",
                "desc": "يسمح: بالاطلاع على فواتير وبحث مبيعات كل الموظفين وملخص مبيعات اليوم للمتجر.",
                "risk": "financial",
                "requires": ["history_view_own"],
            },
            {
                "key": "sales_return_own",
                "label": "عمل مرتجع أو تعديل لفاتورة أصدرها هذا الموظف فقط",
                "desc": "يسمح: باسترجاع أصناف أو تعديل فواتير أصدرها الموظف نفسه فقط. يمنع: مرتجع فواتير غيره.",
                "risk": "financial",
                "requires": ["history_view_own"],
            },
            {
                "key": "sales_return",
                "label": "عمل مرتجع أو تعديل لأي فاتورة في المتجر",
                "desc": "يسمح: باسترجاع أصناف من أي فاتورة لأي موظف وإعادتها للمخزون.",
                "risk": "critical",
                "requires": ["history_view_all"],
            },
            {
                "key": "sales_post_discount",
                "label": "إضافة أو تعديل خصم على فاتورة مدفوعة مسبقاً",
                "desc": "يسمح: بتعديل قيمة الخصم لفاتورة صدرت بالفعل وتحديث دفتر العميل إن كانت آجلة.",
                "risk": "critical",
                "requires": ["history_view_own"],
            },
        ],
    },
    {
        "key": "quotes",
        "title": "المبيعات الرسمية وعروض الأسعار (A4)",
        "icon": "description",
        "color": "#0284c7",
        "perms": [
            {
                "key": "quotes_view",
                "label": "دخول صفحة عروض الأسعار وفواتير A4",
                "desc": "يسمح: باستعراض عروض الأسعار وفواتير الشركات (بحدود مستنداته ما لم يملك رؤية مبيعات الجميع).",
                "risk": "normal",
                "requires": [],
            },
            {
                "key": "quotes_create_edit",
                "label": "إنشاء وتعديل عروض الأسعار وفواتير A4",
                "desc": "يسمح: بإصدار عرض سعر جديد أو فاتورة B2B رسمية أو تعديل المسودات.",
                "risk": "financial",
                "requires": ["quotes_view"],
            },
            {
                "key": "quotes_convert",
                "label": "تحويل عرض السعر إلى فاتورة مبيعات معتمدة",
                "desc": "يسمح: باعتماد عرض السعر وتحويله لفاتورة خصم مخزون وقيد آجل.",
                "risk": "critical",
                "requires": ["quotes_view", "quotes_create_edit"],
            },
            {
                "key": "quotes_cancel_delete",
                "label": "إلغاء أو حذف عروض الأسعار",
                "desc": "يسمح: بإلغاء عروض الأسعار النشطة أو حذف المسودات غير المحولة.",
                "risk": "financial",
                "requires": ["quotes_view"],
            },
        ],
    },
    {
        "key": "customers",
        "title": "العملاء والمديونيات وسندات القبض",
        "icon": "groups",
        "color": "#7c3aed",
        "perms": [
            {
                "key": "customers_quick_pick",
                "label": "اختيار اسم ورقم هاتف العميل عند البيع فقط (بدون مديونية)",
                "desc": "يسمح: باختيار اسم العميل ورقم هاتفه من الإكمال التلقائي في الكاشير أو الصيانة، مع حجب تام للمديونيات والمشتريات.",
                "risk": "normal",
                "requires": [],
            },
            {
                "key": "customers_view",
                "label": "دخول صفحة العملاء (الأسماء والهواتف فقط)",
                "desc": "يسمح: بفتح صفحة قائمة العملاء والبحث فيها دون رؤية المديونيات أو كشوف الحساب إلا بتفعيل صلاحية المديونيات.",
                "risk": "normal",
                "requires": [],
            },
            {
                "key": "customers_debt_view",
                "label": "رؤية المديونيات وكشف حساب العميل والذمم المالية",
                "desc": "يسمح: بالاطلاع على أرصدة الديون وإجمالي المشتريات ودفتر الأستاذ وكشف حساب العميل التفصيلي.",
                "risk": "financial",
                "requires": ["customers_view"],
            },
            {
                "key": "customers_edit",
                "label": "إضافة وتعديل بيانات العملاء (الاسم والهاتف)",
                "desc": "يسمح: بتسجيل عميل جديد أو تعديل اسم ورقم هاتف عميل حالي (بدون تحصيل أموال).",
                "risk": "normal",
                "requires": ["customers_view"],
            },
            {
                "key": "customers_payment",
                "label": "تحصيل مديونيات العملاء وإصدار سندات قبض",
                "desc": "يسمح: باستلام دفعات سداد من مديونية العميل وإصدار سند قبض مالي.",
                "risk": "critical",
                "requires": ["customers_view", "customers_debt_view"],
            },
            {
                "key": "customers_delete",
                "label": "حذف العملاء أو إلغاء/حذف سندات القبض",
                "desc": "يسمح: بحذف سجلات العملاء غير المرتبطين بمديونية أو إلغاء سند قبض صادر.",
                "risk": "critical",
                "requires": ["customers_view", "customers_debt_view"],
            },
        ],
    },
    {
        "key": "installments",
        "title": "نظام الأقساط والمتابعة",
        "icon": "event_repeat",
        "color": "#0ea5e9",
        "perms": [
            {
                "key": "installments_view",
                "label": "دخول نظام الأقساط وعرض العقود والمتأخرات",
                "desc": "يسمح: باستعراض عقود التقسيط وجداول الأقساط وتنبيهات الاستحقاق فقط (دون تحصيل أو إنشاء).",
                "risk": "financial",
                "requires": [],
            },
            {
                "key": "installments_collect",
                "label": "تحصيل دفعات الأقساط وإرسال تذكيرات واتساب",
                "desc": "يسمح: بتسجيل سداد الأقساط وإصدار إيصالات التحصيل وإرسال رسائل التذكير للعملاء.",
                "risk": "critical",
                "requires": ["installments_view"],
            },
            {
                "key": "installments_create",
                "label": "إنشاء عقود تقسيط جديدة أو جدولة فواتير آجلة",
                "desc": "يسمح: بفتح عقد تقسيط جديد وتحديد نظام الفوائد والجدول الزمني.",
                "risk": "critical",
                "requires": ["installments_view"],
            },
            {
                "key": "installments_cancel",
                "label": "إلغاء عقود الأقساط المفتوحة",
                "desc": "يسمح: بإلغاء عقد تقسيط لم يتم التحصيل منه وعكس قيد المديونية والمخزون.",
                "risk": "critical",
                "requires": ["installments_view", "installments_create"],
            },
        ],
    },
    {
        "key": "inventory",
        "title": "المخزون والمنتجات والسيريال",
        "icon": "inventory_2",
        "color": "#059669",
        "perms": [
            {
                "key": "inventory_view",
                "label": "دخول صفحة المخزون وعرض الكميات والنواقص والقيمة",
                "desc": "يسمح: بفتح صفحة المخزون، رؤية الكميات والتصنيفات والنواقص وإحصائيات إجمالي قيمة البضاعة.",
                "risk": "normal",
                "requires": [],
            },
            {
                "key": "inventory_edit",
                "label": "إضافة وتعديل وحذف المنتجات والتصنيفات والصور",
                "desc": "يسمح: بإنشاء منتجات جديدة وتعديل أسعار البيع أو حذف الأصناف وإدارة الفئات.",
                "risk": "financial",
                "requires": ["inventory_view"],
            },
            {
                "key": "inventory_adjust",
                "label": "التعديل اليدوي لكميات المخزون وإضافة سيريال",
                "desc": "يسمح: بزيادة أو إنقاص رصيد المخزون يدوياً (تسوية جردية) وإضافة أرقام تسلسلية.",
                "risk": "critical",
                "requires": ["inventory_view"],
            },
            {
                "key": "serials_view",
                "label": "استعراض سجل الأرقام التسلسلية (Serials)",
                "desc": "يسمح: بالاطلاع على قائمة السيريالات المتاحة والمباعة لكل منتج متتبّع.",
                "risk": "normal",
                "requires": ["inventory_view"],
            },
            {
                "key": "cost_view",
                "label": "رؤية أسعار الشراء (التكلفة) وهوامش الربح",
                "desc": "يسمح: بإظهار سعر التكلفة للشراء وصافي الربح. عند الإغلاق: تُحجب التكلفة تماماً من الخادم والواجهة.",
                "risk": "critical",
                "requires": [],
            },
        ],
    },
    {
        "key": "repair",
        "title": "مركز الصيانة",
        "icon": "build",
        "color": "#d97706",
        "perms": [
            {
                "key": "repair_view",
                "label": "دخول مركز الصيانة وعرض التذاكر وتفاصيلها",
                "desc": "يسمح: بالاطلاع على تذاكر الصيانة وحالاتها وعداد الصيانة النشطة على سطح المكتب.",
                "risk": "normal",
                "requires": [],
            },
            {
                "key": "repair_create",
                "label": "استلام أجهزة جديدة وإنشاء تذاكر صيانة",
                "desc": "يسمح: بفتح تذكرة صيانة جديدة وطباعة إيصال الاستلام للعميل.",
                "risk": "normal",
                "requires": ["repair_view"],
            },
            {
                "key": "repair_edit",
                "label": "تحديث مراحل الصيانة وتعديل التذكرة وإضافة قطع غيار",
                "desc": "يسمح: بتغيير حالة التذكرة (قيد الفحص/تم الإصلاح/تم التسليم)، تعديل التكلفة، وصرف قطع غيار من المخزون.",
                "risk": "financial",
                "requires": ["repair_view"],
            },
            {
                "key": "repair_delete",
                "label": "حذف تذاكر الصيانة غير المسلمة",
                "desc": "يسمح: بحذف تذكرة صيانة وإرجاع قطع الغيار المضافة إلى المخزون.",
                "risk": "critical",
                "requires": ["repair_view", "repair_edit"],
            },
        ],
    },
    {
        "key": "buy_used",
        "title": "شراء الأجهزة المستعملة",
        "icon": "phonelink_setup",
        "color": "#0d9488",
        "perms": [
            {
                "key": "used_view",
                "label": "عرض سجل وإحصائيات الأجهزة المستعملة",
                "desc": "يسمح: بفتح صفحة شراء المستعمل ورؤية السجل وإجمالي مدفوعات اليوم.",
                "risk": "normal",
                "requires": [],
            },
            {
                "key": "used_manage",
                "label": "شراء وتقييم وتعديل الأجهزة المستعملة",
                "desc": "يسمح: بتسجيل عملية شراء جهاز مستعمل من عميل وتعديل بياناته وإدخاله المخزون.",
                "risk": "financial",
                "requires": ["used_view"],
            },
        ],
    },
    {
        "key": "reports",
        "title": "التقارير المالية والرقابة",
        "icon": "bar_chart",
        "color": "#4f46e5",
        "perms": [
            {
                "key": "reports_sales_view",
                "label": "تقارير المبيعات اليومية والشهرية والأكثر مبيعاً",
                "desc": "يسمح: بعرض ملخصات المبيعات والضرائب والمرتجعات والتحصيلات والأصناف الأكثر طلباً.",
                "risk": "financial",
                "requires": [],
            },
            {
                "key": "reports_profit_view",
                "label": "تقرير صافي الأرباح والتكاليف",
                "desc": "يسمح: برؤية إجمالي إيرادات وصافي أرباح المبيعات ومركز الصيانة.",
                "risk": "critical",
                "requires": ["reports_sales_view", "cost_view"],
            },
            {
                "key": "reports_shifts_view",
                "label": "سجل ورديات جميع الموظفين ومراقبة العجز والزيادة",
                "desc": "يسمح: بمراجعة كافة الورديات المفتوحة والمغلقة والمبالغ المعدودة والمتوقعة والفروقات.",
                "risk": "critical",
                "requires": [],
            },
            {
                "key": "reports_movements_view",
                "label": "تقارير حركة المخزون التفصيلية والنواقص",
                "desc": "يسمح: بمتابعة سجل الوارد والمنصرف والتسويات والمنتجات التي وصلت للحد الأدنى.",
                "risk": "normal",
                "requires": [],
            },
        ],
    },
    {
        "key": "admin",
        "title": "إدارة الموظفين وإعدادات النظام والنسخ الاحتياطي",
        "icon": "admin_panel_settings",
        "color": "#0f172a",
        "perms": [
            {
                "key": "staff_view",
                "label": "عرض قائمة الموظفين وصلاحياتهم",
                "desc": "يسمح: بفتح صفحة الموظفين ورؤية الحسابات المسجلة وتفاصيل صلاحياتهم فقط.",
                "risk": "financial",
                "requires": [],
            },
            {
                "key": "staff_manage",
                "label": "إضافة وتعديل وتعطيل وحذف الموظفين وتخصيص الصلاحيات",
                "desc": "يسمح: بإنشاء وتعديل حسابات الموظفين، تغيير PIN، إيقاف الحساب، ومراجعة سجل تعديلات الصلاحيات.",
                "risk": "critical",
                "requires": ["staff_view"],
            },
            {
                "key": "settings_view_edit",
                "label": "تعديل إعدادات المتجر والضريبة والطباعة وطرق الدفع",
                "desc": "يسمح: بتعديل اسم المتجر، الضريبة، وضع الدخول، خيارات المعاينة والطباعة، وقائمة طرق الدفع.",
                "risk": "critical",
                "requires": [],
            },
            {
                "key": "templates_manage",
                "label": "تعديل قوالب وتصاميم الفواتير (80mm / A4)",
                "desc": "يسمح: بتخصيص استوديو الفواتير والشعار والبادئات وعناصر الطباعة.",
                "risk": "financial",
                "requires": [],
            },
            {
                "key": "backups_manage",
                "label": "إنشاء وعرض واستعادة النسخ الاحتياطية لقاعدة البيانات",
                "desc": "يسمح: بأخذ نسخة احتياطية فورية أو استعادة قاعدة البيانات من لقطة سابقة.",
                "risk": "critical",
                "requires": [],
            },
        ],
    },
]

ALL_PERM_KEYS = tuple(
    p["key"] for grp in PERMISSION_GROUPS for p in grp["perms"]
)
PERM_META_MAP = {
    p["key"]: {**p, "group": grp["key"], "group_title": grp["title"]}
    for grp in PERMISSION_GROUPS
    for p in grp["perms"]
}

_STRICT_SET = {"pos_sell", "shift_manage", "receipt_view", "customers_quick_pick"}
STRICT_CASHIER_PERMS = {k: (k in _STRICT_SET) for k in ALL_PERM_KEYS}
DEFAULT_CASHIER_PERMS = dict(STRICT_CASHIER_PERMS)
ALL_ADMIN_PERMS = {k: True for k in ALL_PERM_KEYS}


def _preset_dict(enabled_keys: set[str]) -> dict[str, bool]:
    return {k: (k in enabled_keys) for k in ALL_PERM_KEYS}


DEFAULT_ROLE_PRESETS = [
    {
        "key": "cashier_strict",
        "name": "كاشير مبيعات فقط (صارم)",
        "description": "نقاط البيع نقدي ومحفظة + ورديته (جرد أعمى) + طباعة إيصالاته + اختيار اسم/هاتف العميل فقط دون أي مديونيات أو تقارير أو خصومات.",
        "badge_color": "emerald",
        "perms": _preset_dict({"pos_sell", "shift_manage", "receipt_view", "customers_quick_pick"}),
    },
    {
        "key": "senior_cashier",
        "name": "كاشير متقدم / مشرف وردية",
        "description": "كاشير يملك خصم الصنف والفاتورة، رؤية كشف إغلاق الوردية، استرجاع فواتيره، والبحث في سجل مبيعاته مع إرسال واتساب.",
        "badge_color": "blue",
        "perms": _preset_dict({
            "pos_sell", "shift_manage", "shift_summary_view", "receipt_view",
            "customers_quick_pick", "pos_item_discount", "pos_invoice_discount",
            "pos_whatsapp", "history_view_own", "sales_return_own",
        }),
    },
    {
        "key": "sales_b2b",
        "name": "موظف مبيعات وعروض أسعار A4",
        "description": "إنشاء وإدارة عروض الأسعار وفواتير A4 والبيع الآجل واستعراض وطباعة مستندات المبيعات والعملاء.",
        "badge_color": "sky",
        "perms": _preset_dict({
            "pos_sell", "pos_credit_sale", "pos_whatsapp", "shift_manage", "shift_summary_view",
            "receipt_view", "history_view_own", "quotes_view", "quotes_create_edit",
            "quotes_convert", "quotes_cancel_delete", "customers_quick_pick",
            "customers_view", "customers_edit", "customers_debt_view",
        }),
    },
    {
        "key": "inventory_clerk",
        "name": "أمين مخزون ومشتريات",
        "description": "إدارة المنتجات والفئات والكميات والأرقام التسلسلية ومراجعة حركة المخزون والنواقص وشراء الأجهزة المستعملة.",
        "badge_color": "teal",
        "perms": _preset_dict({
            "inventory_view", "inventory_edit", "inventory_adjust", "serials_view",
            "cost_view", "reports_movements_view", "used_view", "used_manage",
        }),
    },
    {
        "key": "technician",
        "name": "فني ومهندس صيانة",
        "description": "دخول مركز الصيانة، استلام الأجهزة، تحديث مراحل الإصلاح وصرف قطع الغيار، مع اختيار العميل بالاسم/الهاتف فقط.",
        "badge_color": "amber",
        "perms": _preset_dict({
            "repair_view", "repair_create", "repair_edit", "customers_quick_pick",
            "used_view", "used_manage",
        }),
    },
    {
        "key": "accountant",
        "name": "محاسب وتحصيل وتقارير",
        "description": "كامل التقارير والأرباح وسجل الورديات ومراجعة كل المبيعات، مع كشوف حساب العملاء وسندات القبض وتحصيل الأقساط.",
        "risk": "financial",
        "badge_color": "indigo",
        "perms": _preset_dict({
            "history_view_own", "history_view_all", "receipt_view", "quotes_view",
            "customers_quick_pick", "customers_view", "customers_debt_view",
            "customers_edit", "customers_payment",
            "installments_view", "installments_collect", "installments_create",
            "inventory_view", "cost_view",
            "reports_sales_view", "reports_profit_view", "reports_shifts_view", "reports_movements_view",
        }),
    },
    {
        "key": "store_manager",
        "name": "مدير تشغيل المتجر (صلاحيات شاملة عدا المالك)",
        "description": "جميع الصلاحيات التشغيلية والمالية والإدارية باستثناء دور المالك الرئيسي.",
        "badge_color": "purple",
        "perms": dict(ALL_ADMIN_PERMS),
    },
]


def parse_user_perms(role: str, raw_perms: str | dict | None) -> dict[str, bool]:
    """تحليل وتطبيع قاموس الصلاحيات دائماً إلى المفاتيح الـ 49 المعتمدة."""
    if role == "admin":
        return dict(ALL_ADMIN_PERMS)
    base = dict(DEFAULT_CASHIER_PERMS)
    loaded = None
    if isinstance(raw_perms, dict):
        loaded = raw_perms
    elif raw_perms:
        try:
            loaded = json.loads(raw_perms)
        except Exception:
            loaded = None
    if isinstance(loaded, dict):
        for k in base:
            if k in loaded:
                base[k] = bool(loaded[k])
    return base
