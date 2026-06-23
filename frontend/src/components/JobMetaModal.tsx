// Shared dialog for entering/editing a job's user metadata (과제/타입/리비전).
// Used both when uploading a new ODB++ file and when editing an existing row.
// Each field is an AutoComplete: type a new value or pick a previously-used one.

import { useEffect } from "react";
import { AutoComplete, Form, Modal } from "antd";
import type { JobMeta, MetaOptions } from "../types";

// Common board types seeded as suggestions (free entry still allowed).
const PRESET_TYPES = ["Main", "Secondary", "Sub", "IF Sub", "FPCB"];

// Common revisions seeded as suggestions (free entry still allowed).
const PRESET_REVISIONS = ["0.0", "0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "FINAL"];

const EMPTY: JobMeta = { project: "", model: "", board_type: "", revision: "" };

function toOptions(values: string[]): { value: string }[] {
  return values.map((v) => ({ value: v }));
}

const filterOption = (input: string, option?: { value: string }) =>
  (option?.value ?? "").toLowerCase().includes(input.toLowerCase());

export default function JobMetaModal({
  open,
  title,
  okText = "확인",
  initial,
  options,
  confirmLoading,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  okText?: string;
  initial?: JobMeta;
  options?: MetaOptions;
  confirmLoading?: boolean;
  onConfirm: (meta: JobMeta) => void;
  onCancel: () => void;
}) {
  const [form] = Form.useForm<JobMeta>();

  useEffect(() => {
    if (open) form.setFieldsValue({ ...EMPTY, ...(initial ?? {}) });
  }, [open, initial, form]);

  // Presets first, then any previously-used values not already in the presets.
  const typeOptions = toOptions([
    ...PRESET_TYPES,
    ...(options?.board_types ?? []).filter((v) => !PRESET_TYPES.includes(v)),
  ]);
  const revisionOptions = toOptions([
    ...PRESET_REVISIONS,
    ...(options?.revisions ?? []).filter((v) => !PRESET_REVISIONS.includes(v)),
  ]);

  const submit = () => {
    const v = form.getFieldsValue();
    onConfirm({
      project: (v.project ?? "").trim(),
      model: (v.model ?? "").trim(),
      board_type: (v.board_type ?? "").trim(),
      revision: (v.revision ?? "").trim(),
    });
  };

  return (
    <Modal
      open={open}
      title={title}
      okText={okText}
      cancelText="취소"
      confirmLoading={confirmLoading}
      onOk={submit}
      onCancel={onCancel}
      destroyOnClose
    >
      <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
        <Form.Item label="과제" name="project">
          <AutoComplete
            options={toOptions(options?.projects ?? [])}
            filterOption={filterOption}
            placeholder="과제명 입력 또는 기존 값 선택"
            allowClear
          />
        </Form.Item>
        <Form.Item label="모델" name="model">
          <AutoComplete
            options={toOptions(options?.models ?? [])}
            filterOption={filterOption}
            placeholder="모델명 입력 또는 기존 값 선택"
            allowClear
          />
        </Form.Item>
        <Form.Item label="타입" name="board_type">
          <AutoComplete
            options={typeOptions}
            filterOption={filterOption}
            placeholder="Main / Secondary / Sub / IF Sub / FPCB …"
            allowClear
          />
        </Form.Item>
        <Form.Item label="리비전" name="revision">
          <AutoComplete
            options={revisionOptions}
            filterOption={filterOption}
            placeholder="0.0 / 0.1 / … / FINAL"
            allowClear
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
