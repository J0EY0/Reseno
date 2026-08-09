import { AvatarPreview } from "@/components/preview/resume-preview-media";
import {
  getDiffClassName,
  getDiffLabel,
  getResumeFallbackName,
} from "@/components/preview/resume-preview-model";
import type { AppMessages } from "@/i18n";
import {
  createContactHref,
  normalizeContactFieldType,
} from "@/lib/contact-links";
import { cn } from "@/lib/utils";
import type {
  ResumeBasicInfo,
  ResumeDraftDiff,
  ResumeTemplateLayout,
  ResumeTemplateSettings,
} from "@/types/resume";

interface ContactItem {
  href?: string;
  id: string;
  text: string;
}

function getContactItems(basic: ResumeBasicInfo) {
  const items: ContactItem[] = [
    {
      id: "phone",
      text: basic.phone.trim(),
      href: createContactHref("phone", basic.phone) ?? undefined,
    },
    {
      id: "email",
      text: basic.email.trim(),
      href: createContactHref("email", basic.email) ?? undefined,
    },
    { id: "location", text: basic.location.trim() },
    ...basic.customFields.map((field) => {
      const label = field.label.trim();
      const value = field.value.trim();

      return {
        id: `custom-${field.id}`,
        text: label && value ? `${label}: ${value}` : value || label,
        href: value
          ? createContactHref(normalizeContactFieldType(field.type), value) ??
            undefined
          : undefined,
      };
    }),
  ];

  return items.filter((item) => item.text);
}

function ContactItemText({
  enableLink,
  item,
}: {
  enableLink: boolean;
  item: ContactItem;
}) {
  if (!enableLink || !item.href) {
    return <span>{item.text}</span>;
  }

  const opensNewTab =
    item.href.startsWith("http://") || item.href.startsWith("https://");

  return (
    <a
      href={item.href}
      className="text-inherit no-underline hover:underline"
      target={opensNewTab ? "_blank" : undefined}
      rel={opensNewTab ? "noreferrer noopener" : undefined}
    >
      {item.text}
    </a>
  );
}

function ContactLine({
  className,
  enableLinks,
  items,
}: {
  className?: string;
  enableLinks: boolean;
  items: ContactItem[];
}) {
  if (items.length === 0) {
    return null;
  }

  return (
    <div
      className={cn(
        "flex flex-wrap justify-center gap-x-3 gap-y-1",
        className,
      )}
    >
      {items.map((item, index) => (
        <span key={item.id}>
          <ContactItemText item={item} enableLink={enableLinks} />
          {index < items.length - 1 ? (
            <span className="resume-tone-subtle ml-3">|</span>
          ) : null}
        </span>
      ))}
    </div>
  );
}

interface BasicInfoProps {
  basic: ResumeBasicInfo;
  enableContactLinks: boolean;
  layout: ResumeTemplateLayout;
  settings: ResumeTemplateSettings;
  summaryDiff?: ResumeDraftDiff;
  t: AppMessages;
}

export function StandardBasicInfo({
  basic,
  enableContactLinks,
  layout,
  settings,
  summaryDiff,
  t,
}: BasicInfoProps) {
  const isProfile = layout.basicInfo === "profile";
  const isLeftAligned = layout.basicInfo === "left";
  const isSplit = layout.basicInfo === "split";
  const avatarPosition = layout.avatarPosition;
  const hasAvatar = avatarPosition !== "none" && Boolean(basic.avatar.trim());
  const shouldFloatSideAvatar =
    hasAvatar && layout.basicInfo === "centered" && avatarPosition !== "center";
  const contactItems = getContactItems(basic);
  const avatar = hasAvatar ? (
    <AvatarPreview
      basic={basic}
      layout={layout}
      t={t}
      className={cn(
        shouldFloatSideAvatar &&
          (avatarPosition === "left"
            ? "absolute left-0 top-0 z-10"
            : "absolute right-0 top-0 z-10"),
        isProfile && avatarPosition === "center"
          ? "size-[112px]"
          : layout.avatarShape === "circle"
            ? "size-[108px]"
            : isProfile
              ? "size-[108px]"
              : "h-[120px] w-[96px]",
      )}
    />
  ) : null;
  const identityContent = (
    <>
      <h1
        className="font-extrabold tracking-[-0.04em]"
        style={{
          color: isProfile ? settings.bodyColor : settings.headingColor,
          fontSize: `${settings.nameScale}em`,
        }}
      >
        {basic.name || getResumeFallbackName(t)}
      </h1>
      {basic.headline ? (
        <p
          className={cn(
            "resume-tone-muted mt-2 font-medium",
            isProfile && "tracking-[0.08em]",
          )}
          style={{ fontSize: `${Math.max(0.85, settings.bodyScale)}em` }}
        >
          {basic.headline}
        </p>
      ) : null}
    </>
  );
  const contactContent = (
    <ContactLine
      items={contactItems}
      enableLinks={enableContactLinks}
      className="resume-tone-body mt-3"
    />
  );
  const infoContent = (
    <>
      {identityContent}
      {contactContent}
    </>
  );
  const basicInfoContent = isSplit ? (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)] items-end gap-8">
      <div className="text-left">{identityContent}</div>
      <div className="min-w-0">
        <ContactLine
          items={contactItems}
          enableLinks={enableContactLinks}
          className="resume-tone-body mt-0 justify-end text-right"
        />
      </div>
    </div>
  ) : (
    <div
      className={cn(
        "min-w-0",
        isLeftAligned ||
          (isProfile && hasAvatar && avatarPosition === "left")
          ? "text-left"
          : "mx-auto text-center",
      )}
    >
      {infoContent}
    </div>
  );

  return (
    <header
      className={cn(
        "relative grid gap-4",
        isProfile && "overflow-hidden rounded-2xl px-5 py-5",
      )}
      style={
        isProfile
          ? {
              background: `linear-gradient(180deg, ${settings.dividerColor}18, transparent 68%)`,
            }
          : undefined
      }
    >
      {avatar && avatarPosition === "center" ? (
        <div className="grid justify-items-center gap-3 text-center">
          {avatar}
          {basicInfoContent}
        </div>
      ) : shouldFloatSideAvatar ? (
        <>
          {avatar}
          {basicInfoContent}
        </>
      ) : avatar ? (
        <div
          className={cn(
            "grid items-start gap-5",
            avatarPosition === "left"
              ? "grid-cols-[auto_minmax(0,1fr)]"
              : "grid-cols-[minmax(0,1fr)_auto]",
          )}
        >
          {avatarPosition === "left" ? avatar : null}
          <div className="min-w-0">{basicInfoContent}</div>
          {avatarPosition !== "left" ? avatar : null}
        </div>
      ) : (
        basicInfoContent
      )}

      {basic.summary ? (
        <p
          className={cn(
            "resume-tone-body text-left",
            getDiffClassName(summaryDiff),
          )}
          data-resume-diff-kind={summaryDiff?.kind}
          data-resume-diff-label={getDiffLabel(summaryDiff, t)}
          style={{
            fontSize: `${settings.bodyScale}em`,
            lineHeight: settings.bodyLineHeight,
          }}
        >
          {basic.summary}
        </p>
      ) : null}
    </header>
  );
}

export function SidebarBasicInfo({
  basic,
  enableContactLinks,
  layout,
  settings,
  summaryDiff,
  t,
}: BasicInfoProps) {
  const contactItems = getContactItems(basic);
  const avatar =
    layout.avatarPosition === "none" ? null : (
      <AvatarPreview
        basic={basic}
        layout={layout}
        t={t}
        className={cn(
          "mx-auto bg-white/10",
          layout.avatarShape === "circle"
            ? "size-[108px]"
            : "h-[118px] w-[96px]",
        )}
      />
    );

  return (
    <aside
      className="flex min-h-[297mm] flex-col gap-8 px-7 py-10 text-white"
      style={{ backgroundColor: settings.surfaceColor }}
    >
      {avatar}

      <div className="grid gap-2">
        <h1
          className="font-semibold tracking-[-0.03em]"
          style={{ fontSize: `${settings.nameScale}em` }}
        >
          {basic.name || getResumeFallbackName(t)}
        </h1>
        {basic.headline ? (
          <p
            className="text-white/75"
            style={{ fontSize: `${settings.bodyScale}em` }}
          >
            {basic.headline}
          </p>
        ) : null}
      </div>

      {contactItems.length > 0 ? (
        <div className="grid gap-2">
          <p
            className="font-semibold"
            style={{ fontSize: `${settings.sectionTitleScale}em` }}
          >
            {t.resumePreviewContactTitle}
          </p>
          <div
            className="grid gap-1.5 text-white/90"
            style={{
              fontSize: `${settings.metaScale}em`,
              lineHeight: settings.bodyLineHeight,
            }}
          >
            {contactItems.map((item) => (
              <ContactItemText
                key={item.id}
                item={item}
                enableLink={enableContactLinks}
              />
            ))}
          </div>
        </div>
      ) : null}

      {basic.summary ? (
        <div className="grid gap-2">
          <p
            className="font-semibold"
            style={{ fontSize: `${settings.sectionTitleScale}em` }}
          >
            {t.resumePreviewSummaryTitle}
          </p>
          <p
            className={cn("text-white/80", getDiffClassName(summaryDiff))}
            data-resume-diff-kind={summaryDiff?.kind}
            data-resume-diff-label={getDiffLabel(summaryDiff, t)}
            style={{
              fontSize: `${settings.bodyScale}em`,
              lineHeight: settings.bodyLineHeight,
            }}
          >
            {basic.summary}
          </p>
        </div>
      ) : null}
    </aside>
  );
}
