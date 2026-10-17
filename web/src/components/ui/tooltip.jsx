import * as React from 'react';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import { cn } from '../../lib/utils.js';

export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export const TooltipContent = React.forwardRef(function TooltipContent({ className, sideOffset = 6, ...props }, ref) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        ref={ref}
        sideOffset={sideOffset}
        className={cn('z-50 max-w-xs rounded-md bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-md border border-border', className)}
        {...props}
      />
    </TooltipPrimitive.Portal>
  );
});
