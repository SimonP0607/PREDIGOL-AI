import { Toaster as Sonner } from "sonner";

type ToasterProps = React.ComponentProps<typeof Sonner>;

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      className="toaster group"
      // every toast the same: four seconds, the same card; Sonner moves it in and out and the reduced-motion rule stills it
      duration={4000}
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:rounded-control group-[.toaster]:border-border-strong group-[.toaster]:bg-popover group-[.toaster]:text-sm group-[.toaster]:font-semibold group-[.toaster]:text-foreground group-[.toaster]:shadow-[0_18px_40px_-16px_rgb(0_0_0/0.95)]",
          description: "group-[.toast]:text-muted-foreground",
          actionButton: "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton: "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
