import * as React from 'react';
import * as CheckboxPrimitive from '@radix-ui/react-checkbox';
import { cn } from '../../lib/utils.js';

export const Checkbox = React.forwardRef(function Checkbox({ className, ...props }, ref) {
  return (
    <CheckboxPrimitive.Root
      ref={ref}
      className={cn(
        'peer size-4 shrink-0 rounded-sm border border-input bg-card focus-visible:outline-2 focus-visible:outline-ring data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground disabled:opacity-50',
        className,
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator className="flex items-center justify-center text-xs leading-none">✓</CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
});
