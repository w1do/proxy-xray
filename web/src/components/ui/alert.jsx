import { cva } from 'class-variance-authority';
import { cn } from '../../lib/utils.js';

const alertVariants = cva('relative w-full rounded-lg border p-4 text-sm', {
  variants: {
    variant: {
      default: 'border-border bg-card text-card-foreground',
      warning: 'border-warning bg-warning/15 text-foreground',
      destructive: 'border-destructive bg-destructive/10 text-foreground',
      success: 'border-success bg-success/10 text-foreground',
    },
  },
  defaultVariants: { variant: 'default' },
});

export function Alert({ className, variant, ...props }) {
  return <div role="alert" className={cn(alertVariants({ variant }), className)} {...props} />;
}

export function AlertTitle({ className, ...props }) {
  return <p className={cn('mb-1 font-semibold leading-none', className)} {...props} />;
}

export function AlertDescription({ className, ...props }) {
  return <div className={cn('text-sm [&_p]:leading-relaxed', className)} {...props} />;
}
