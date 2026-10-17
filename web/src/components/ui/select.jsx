import * as React from 'react';
import * as SelectPrimitive from '@radix-ui/react-select';
import { cn } from '../../lib/utils.js';

export const Select = SelectPrimitive.Root;
export const SelectValue = SelectPrimitive.Value;

export const SelectTrigger = React.forwardRef(function SelectTrigger({ className, children, ...props }, ref) {
  return (
    <SelectPrimitive.Trigger
      ref={ref}
      className={cn(
        'flex h-9 w-full min-w-0 items-center justify-between gap-2 rounded-md border border-input bg-card px-3 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50',
        className,
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon className="text-muted-foreground">▾</SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
});

export const SelectContent = React.forwardRef(function SelectContent({ className, children, ...props }, ref) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        ref={ref}
        position="popper"
        className={cn('z-50 min-w-[8rem] overflow-hidden rounded-md border border-border bg-popover text-popover-foreground shadow-md', className)}
        {...props}
      >
        <SelectPrimitive.Viewport className="p-1">{children}</SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
});

export const SelectItem = React.forwardRef(function SelectItem({ className, children, ...props }, ref) {
  return (
    <SelectPrimitive.Item
      ref={ref}
      className={cn('relative flex cursor-pointer select-none items-center rounded-sm py-1.5 pr-3 pl-7 text-sm outline-none data-[highlighted]:bg-accent', className)}
      {...props}
    >
      <span className="absolute left-2 text-xs">
        <SelectPrimitive.ItemIndicator>✓</SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  );
});
