"""
Base Agent - 所有Agent继承的基类

提供学科验证等共享功能
"""

from abc import ABC, abstractmethod
from typing import List, Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class BaseAgent(ABC):
    """
    Agent基类

    所有模块的Agent都应继承此类,以获得:
    - 学科验证功能
    - 统一的日志记录
    - 错误处理机制
    """

    def __init__(self, subjects: List[str]):
        """
        初始化Agent

        Args:
            subjects: 当前模块支持的学科列表
        """
        self.subjects = subjects
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info(f"Initialized {self.__class__.__name__} for subjects: {subjects}")

    def validate_subject(self, subject: str) -> bool:
        """
        验证学科是否在当前模块支持范围内

        Args:
            subject: 学科名称(如: math, physics, chinese等)

        Returns:
            bool: 如果学科受支持返回True,否则返回False

        Example:
            >>> agent = SomeAgent(subjects=["math", "physics"])
            >>> agent.validate_subject("math")
            True
            >>> agent.validate_subject("chemistry")
            False
        """
        is_valid = subject.lower() in [s.lower() for s in self.subjects]
        if not is_valid:
            self.logger.warning(
                f"Subject '{subject}' is not supported by this module. "
                f"Supported subjects: {self.subjects}"
            )
        return is_valid

    def validate_subject_or_raise(self, subject: str) -> None:
        """
        验证学科,如果不支持则抛出异常

        Args:
            subject: 学科名称

        Raises:
            ValueError: 如果学科不在支持列表中

        Example:
            >>> agent.validate_subject_or_raise("math")  # OK
            >>> agent.validate_subject_or_raise("chemistry")  # Raises ValueError
        """
        if not self.validate_subject(subject):
            raise ValueError(
                f"Subject '{subject}' is not supported by this module. "
                f"Supported subjects: {self.subjects}"
            )

    @abstractmethod
    async def process(self, **kwargs: Any) -> Dict[str, Any]:
        """
        处理Agent任务的抽象方法

        子类必须实现此方法来定义具体的处理逻辑

        Args:
            **kwargs: 处理所需的参数(根据Agent类型而不同)

        Returns:
            Dict[str, Any]: 处理结果

        Raises:
            NotImplementedError: 如果子类未实现此方法
        """
        raise NotImplementedError("Subclass must implement process() method")

    def get_supported_subjects(self) -> List[str]:
        """
        获取当前Agent支持的学科列表

        Returns:
            List[str]: 学科列表
        """
        return self.subjects.copy()

    def is_subject_supported(self, subject: str) -> bool:
        """
        检查学科是否受支持 (validate_subject的别名)

        Args:
            subject: 学科名称

        Returns:
            bool: 是否支持该学科
        """
        return self.validate_subject(subject)

    def log_info(self, message: str, **kwargs: Any) -> None:
        """
        记录info级别日志

        Args:
            message: 日志消息
            **kwargs: 额外的日志上下文
        """
        if kwargs:
            self.logger.info(f"{message} | Context: {kwargs}")
        else:
            self.logger.info(message)

    def log_warning(self, message: str, **kwargs: Any) -> None:
        """
        记录warning级别日志

        Args:
            message: 日志消息
            **kwargs: 额外的日志上下文
        """
        if kwargs:
            self.logger.warning(f"{message} | Context: {kwargs}")
        else:
            self.logger.warning(message)

    def log_error(self, message: str, exception: Optional[Exception] = None, **kwargs: Any) -> None:
        """
        记录error级别日志

        Args:
            message: 日志消息
            exception: 异常对象(可选)
            **kwargs: 额外的日志上下文
        """
        if exception:
            self.logger.error(f"{message} | Error: {str(exception)} | Context: {kwargs}", exc_info=True)
        elif kwargs:
            self.logger.error(f"{message} | Context: {kwargs}")
        else:
            self.logger.error(message)

class BaseQuestionAgent(BaseAgent):
    """
    错题相关Agent的基类

    提供错题处理的通用功能
    """

    def __init__(self, subjects: List[str]):
        super().__init__(subjects)

    async def validate_question_data(self, question_data: Dict[str, Any]) -> bool:
        """
        验证错题数据的完整性

        Args:
            question_data: 错题数据字典

        Returns:
            bool: 数据是否有效
        """
        required_fields = ["subject", "question_body"]
        for field in required_fields:
            if field not in question_data or not question_data[field]:
                self.log_warning(f"Missing required field: {field}", data=question_data)
                return False

        # 验证学科
        subject = question_data.get("subject")
        if not self.validate_subject(subject):
            return False

        return True

class BaseOCRAgent(BaseAgent):
    """
    OCR相关Agent的基类

    提供OCR处理的通用功能
    """

    def __init__(self, subjects: List[str]):
        super().__init__(subjects)

    async def validate_image_file(self, file_path: str) -> bool:
        """
        验证图片文件是否存在且可读

        Args:
            file_path: 图片文件路径

        Returns:
            bool: 文件是否有效
        """
        import os
        if not os.path.exists(file_path):
            self.log_error(f"Image file not found: {file_path}")
            return False

        if not os.path.isfile(file_path):
            self.log_error(f"Path is not a file: {file_path}")
            return False

        # 检查文件扩展名
        valid_extensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]
        _, ext = os.path.splitext(file_path)
        if ext.lower() not in valid_extensions:
            self.log_warning(f"Unusual file extension: {ext}", file_path=file_path)

        return True
