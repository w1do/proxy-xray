import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { cn } from '../../lib/utils.js';

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export const DialogContent = React.forwardRef(function DialogContent({ className, children, ...props }, ref) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50" />
      <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 pointer-events-none">
        <DialogPrimitive.Content
          ref={ref}
          className={cn('pointer-events-auto mt-8 w-full max-w-2xl rounded-lg border border-border bg-card p-5 text-card-foreground shadow-lg', className)}
          {...props}
        >
          {children}
        </DialogPrimitive.Content>
      </div>
    </DialogPrimitive.Portal>
  );
});

export function DialogHeader({ className, ...props }) {
  return <div className={cn('mb-4 flex flex-col gap-1', className)} {...props} />;
}

export const DialogTitle = React.forwardRef(function DialogTitle({ className, ...props }, ref) {
  return <DialogPrimitive.Title ref={ref} className={cn('text-base font-semibold', className)} {...props} />;
});

export const DialogDescription = React.forwardRef(function DialogDescription({ className, ...props }, ref) {
  return <DialogPrimitive.Description ref={ref} className={cn('text-sm text-muted-foreground', className)} {...props} />;
});
